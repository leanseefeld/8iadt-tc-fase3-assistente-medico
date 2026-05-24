"""Nó de guardrail: valida e filtra a resposta antes de entregá-la ao cliente."""

from __future__ import annotations

import json as _json
import logging
import re
import time
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage

from assistente_medico_api.config import Settings, resolve_runtime_path
from assistente_medico_api.graph.context_formatting import format_context_block
from assistente_medico_api.graph.rag_enhancement import append_audit_jsonl
from assistente_medico_api.graph.nodes.generate import _build_llm
from assistente_medico_api.graph.state import CHAT_HISTORY_MAX_ITEMS, ChatRAGState
from assistente_medico_api.observability.audit import audit, truncate

GuardrailVerdict = Literal["SEGURO", "AVISO", "BLOQUEAR"]
_logger = logging.getLogger(__name__)

_SAFE_BLOCKED_MESSAGE = (
    "Não consigo fornecer essa informação de forma segura neste contexto. "
    "Consulte o protocolo clínico aplicável ou o médico responsável."
)

_DISCLAIMER = (
    "\n\n⚠️ *Nota: Esta resposta contém recomendações que devem ser avaliadas "
    "pelo médico responsável antes de qualquer aplicação clínica.*"
)

_CLASSIFIER_SYSTEM = """\
Você é um auditor de segurança clínica. Analise a resposta do assistente médico e retorne \
SOMENTE um objeto JSON no formato exato (sem markdown, sem texto adicional):
{"verdict": "SEGURO"|"AVISO"|"BLOQUEAR", "reason": "<motivo em até 100 chars>"}

Critérios:
- SEGURO: orienta sem mencionar qualquer dose numérica, posologia ou esquema terapêutico específico.
- AVISO: menciona doses ou esquemas numéricos (mesmo com ressalvas ou atribuídos a protocolo oficial).
- BLOQUEAR: prescrição direta (dose + medicamento + via/posologia), automedicação ou dado clínico fabricado.\
"""

_STRICT_SYSTEM_PROMPT = """\
Você é um assistente clínico de apoio a médicos no Brasil.
RESTRIÇÃO ABSOLUTA: nunca mencione doses, posologias, esquemas terapêuticos ou instruções \
de uso de medicamentos. Quando necessário, oriente o médico a consultar o PCDT correspondente \
ou um especialista competente.
Responda em português do Brasil, de forma objetiva e profissional.\
"""

_KEYWORD_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b\d+\s*(?:mg|mcg|µg|UI|mL|g)\b", re.IGNORECASE),
    re.compile(r"\b(?:tome|tomar|administre|administrar|prescreva|prescrever)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:dose\s+de|posologia|esquema\s+terapêutico|via\s+(?:oral|intravenosa|subcutânea|intramuscular))\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b\d+\s*(?:comprimido|ampola|frasco|sachê|cápsula)s?\b", re.IGNORECASE),
]


def _check_with_keywords(answer: str) -> tuple[bool, str]:
    """Fallback determinístico para classificar resposta prescritiva."""
    for pattern in _KEYWORD_PATTERNS:
        match = pattern.search(answer)
        if match:
            return True, f"padrão prescritivo detectado: '{match.group()}'"
    return False, ""


async def _classify_with_llm(answer: str, settings: Settings) -> tuple[GuardrailVerdict, str]:
    """Classifica a resposta com LLM e retorna um veredicto estruturado."""
    llm = _build_llm(settings)
    result = await llm.ainvoke(
        [SystemMessage(content=_CLASSIFIER_SYSTEM), HumanMessage(content=answer[:2000])]
    )

    raw = (getattr(result, "content", None) or "").strip()
    if isinstance(raw, list):
        raw = "".join(str(p) for p in raw)

    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not json_match:
        raise ValueError(f"LLM não retornou JSON válido: {raw[:120]}")

    data = _json.loads(json_match.group())
    verdict: GuardrailVerdict = data.get("verdict", "SEGURO")
    if verdict not in ("SEGURO", "AVISO", "BLOQUEAR"):
        verdict = "SEGURO"
    reason = str(data.get("reason", ""))[:140]
    return verdict, reason


async def _regenerate_strict(state: ChatRAGState, settings: Settings) -> str:
    """Regenera a resposta com prompt endurecido usando ainvoke."""
    llm = _build_llm(settings)
    docs = state.get("retrieved_docs") or []
    context = format_context_block(docs) if docs else "(Nenhum trecho recuperado.)"
    query = state.get("query") or ""

    human = (
        f"Pergunta do médico:\n{query}\n\n"
        f"Contexto (trechos PCDT):\n{context}\n\n"
        "Responda sem mencionar doses, posologias ou esquemas terapêuticos específicos."
    )
    result = await llm.ainvoke(
        [SystemMessage(content=_STRICT_SYSTEM_PROMPT), HumanMessage(content=human)]
    )
    content = getattr(result, "content", None) or ""
    if isinstance(content, list):
        content = "".join(str(p) for p in content)
    return str(content).strip()


def _audit_guardrail(
    *,
    event: str,
    level: int,
    patient_id: str | None,
    query: str,
    answer: str,
    reason: str,
    classifier_verdict: str,
    latency_ms: float,
) -> None:
    """Registra auditoria do guardrail sem expor a resposta completa."""
    audit(
        event,
        kind="rag.guardrail",
        level=level,
        latency_ms=latency_ms,
        patient_id=patient_id,
        query_snippet=truncate(query),
        answer_snippet=truncate(answer),
        reason=truncate(reason, 240),
        classifier_verdict=classifier_verdict,
    )


async def guardrail_node(state: ChatRAGState, settings: Settings) -> dict:
    """Classifica a resposta final e aplica a política de segurança clínica."""
    t0 = time.perf_counter()
    original_answer = state.get("answer") or ""
    patient_id_raw = state.get("patient_id") or ""
    patient_id = patient_id_raw or None
    query = state.get("query") or ""
    steps = list(state.get("reasoning_steps") or [])
    hist = list(state.get("chat_history") or [])

    def _elapsed_ms() -> float:
        return round((time.perf_counter() - t0) * 1000, 2)

    try:
        verdict, reason = await _classify_with_llm(original_answer, settings)
    except Exception as exc:
        audit(
            "guardrail_classifier_failed",
            kind="rag.guardrail",
            level=logging.WARNING,
            patient_id=patient_id,
            latency_ms=_elapsed_ms(),
            query_snippet=truncate(query),
            answer_snippet=truncate(original_answer),
            error=truncate(str(exc), 240),
        )
        blocked, kw_reason = _check_with_keywords(original_answer)
        verdict = "BLOQUEAR" if blocked else "SEGURO"
        reason = kw_reason or "classificação por keywords (LLM indisponível)"

    final_answer = original_answer
    guardrail_status: str

    if verdict == "SEGURO":
        guardrail_status = "safe"
        steps.append("Guardrail: resposta classificada como segura.")
        _audit_guardrail(
            event="guardrail_safe",
            level=logging.DEBUG,
            patient_id=patient_id,
            query=query,
            answer=original_answer,
            reason=reason,
            classifier_verdict=verdict,
            latency_ms=_elapsed_ms(),
        )
    elif verdict == "AVISO":
        guardrail_status = "warned"
        final_answer = original_answer + _DISCLAIMER
        steps.append("Guardrail: disclaimer adicionado à resposta.")
        _audit_guardrail(
            event="guardrail_warned",
            level=logging.INFO,
            patient_id=patient_id,
            query=query,
            answer=original_answer,
            reason=reason,
            classifier_verdict=verdict,
            latency_ms=_elapsed_ms(),
        )
    else:
        steps.append(f"Guardrail: resposta bloqueada ({reason}). Tentando regenerar.")
        _audit_guardrail(
            event="guardrail_blocked",
            level=logging.WARNING,
            patient_id=patient_id,
            query=query,
            answer=original_answer,
            reason=reason,
            classifier_verdict=verdict,
            latency_ms=_elapsed_ms(),
        )

        try:
            regen = await _regenerate_strict(state, settings)
            try:
                regen_verdict, regen_reason = await _classify_with_llm(regen, settings)
            except Exception:
                blocked, kw_reason = _check_with_keywords(regen)
                regen_verdict = "BLOQUEAR" if blocked else "SEGURO"
                regen_reason = kw_reason or "classificação por keywords (LLM indisponível)"

            if regen_verdict == "BLOQUEAR":
                final_answer = _SAFE_BLOCKED_MESSAGE
                guardrail_status = "blocked"
                steps.append("Guardrail: regeneração ainda bloqueada; resposta substituída.")
                _audit_guardrail(
                    event="guardrail_regenerated_blocked",
                    level=logging.WARNING,
                    patient_id=patient_id,
                    query=query,
                    answer=regen,
                    reason=regen_reason,
                    classifier_verdict=regen_verdict,
                    latency_ms=_elapsed_ms(),
                )
            else:
                final_answer = regen
                guardrail_status = "regenerated"
                steps.append("Guardrail: resposta regenerada com sucesso.")
                _audit_guardrail(
                    event="guardrail_regenerated",
                    level=logging.INFO,
                    patient_id=patient_id,
                    query=query,
                    answer=regen,
                    reason=regen_reason,
                    classifier_verdict=regen_verdict,
                    latency_ms=_elapsed_ms(),
                )
        except Exception as exc:
            final_answer = _SAFE_BLOCKED_MESSAGE
            guardrail_status = "blocked"
            steps.append("Guardrail: falha na regeneração; resposta segura padrão aplicada.")
            audit(
                "guardrail_regen_failed",
                kind="rag.guardrail",
                level=logging.ERROR,
                patient_id=patient_id,
                query_snippet=truncate(query),
                error=truncate(str(exc), 240),
            )

    hist.append({"role": "assistant", "content": final_answer})
    if len(hist) > CHAT_HISTORY_MAX_ITEMS:
        hist = hist[-CHAT_HISTORY_MAX_ITEMS:]

    audit(
        "guardrail_done",
        kind="rag.guardrail",
        latency_ms=_elapsed_ms(),
        patient_id=patient_id,
        guardrail_status=guardrail_status,
        reason=truncate(reason, 240),
    )

    return {
        "answer": final_answer,
        "guardrail_status": guardrail_status,
        "guardrail_reason": reason,
        "reasoning_steps": steps,
        "chat_history": hist,
        "guardrail_result": {
            "verdict": verdict,
            "reason": reason,
            "status": guardrail_status,
        },
    }
