"""Nó de guardrail: classifica e filtra respostas do LLM antes de enviá-las ao cliente."""

from __future__ import annotations

import json as _json
import logging
import re
import time
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage

from assistente_medico_api.config import Settings
from assistente_medico_api.config import resolve_runtime_path
from assistente_medico_api.graph.rag_enhancement import append_audit_jsonl
from assistente_medico_api.graph.nodes.generate import _build_llm
from assistente_medico_api.graph.state import CHAT_HISTORY_MAX_ITEMS, ChatRAGState
from assistente_medico_api.observability.audit import audit, truncate

GuardrailVerdict = Literal["SEGURO", "AVISO", "BLOQUEAR"]

# Mensagem padrão exibida quando o guardrail bloqueia mesmo após regeneração.
_SAFE_BLOCKED_MESSAGE = (
    "Não consigo fornecer essa informação de forma segura neste contexto. "
    "Consulte o protocolo clínico aplicável ou o médico responsável."
)

# Aviso anexado a respostas com veredicto AVISO.
_DISCLAIMER = (
    "\n\n⚠️ *Nota: Esta resposta contém recomendações que devem ser avaliadas "
    "pelo médico responsável antes de qualquer aplicação clínica.*"
)

# Prompt do LLM auditor — resposta esperada: JSON puro sem markdown.
_CLASSIFIER_SYSTEM = """\
Você é um auditor de segurança clínica. Analise a resposta do assistente médico e retorne \
SOMENTE um objeto JSON no formato exato (sem markdown, sem texto adicional):
{"verdict": "SEGURO"|"AVISO"|"BLOQUEAR", "reason": "<motivo em até 100 chars>"}

Critérios:
- SEGURO: orienta sem mencionar qualquer dose numérica, posologia ou esquema terapêutico específico.
- AVISO: menciona doses ou esquemas numéricos (mesmo com ressalvas ou atribuídos a protocolo oficial).
- BLOQUEAR: prescrição direta (dose + medicamento + via/posologia), automedicação ou dado clínico fabricado.\
"""

# System prompt endurecido usado na tentativa de regeneração.
_STRICT_SYSTEM_PROMPT = """\
Você é um assistente clínico de apoio a médicos no Brasil.
RESTRIÇÃO ABSOLUTA: nunca mencione doses, posologias, esquemas terapêuticos ou instruções \
de uso de medicamentos. Quando necessário, oriente o médico a consultar o PCDT correspondente \
ou um especialista competente.
Responda em português do Brasil, de forma objetiva e profissional.\
"""

# Padrões prescritivos detectáveis deterministicamente — usados como fallback se o LLM falhar.
_KEYWORD_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b\d+\s*(?:mg|mcg|µg|UI|mL|g)\b", re.IGNORECASE),
    re.compile(r"\b(?:tome|tomar|administre|administrar|prescreva|prescrever)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:dose\s+de|posologia|esquema\s+terapêutico|via\s+(?:oral|intravenosa|subcutânea|intramuscular))\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b\d+\s*(?:comprimido|ampola|frasco|sachê|cápsula)s?\b", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _check_with_keywords(answer: str) -> tuple[bool, str]:
    """Fallback determinístico: verifica padrões prescritivos por regex."""
    for pattern in _KEYWORD_PATTERNS:
        match = pattern.search(answer)
        if match:
            return True, f"padrão prescritivo detectado: '{match.group()}'"
    return False, ""


async def _classify_with_llm(
    answer: str, settings: Settings
) -> tuple[GuardrailVerdict, str]:
    """
    Chama o LLM auditor para classificar a resposta.
    Lança exceção em falha — o chamador deve recorrer ao fallback por keywords.
    """
    llm = _build_llm(settings)
    # Limita a 2 000 chars para não estourar contexto do classificador.
    result = await llm.ainvoke(
        [SystemMessage(content=_CLASSIFIER_SYSTEM), HumanMessage(content=answer[:2000])]
    )

    raw = (getattr(result, "content", None) or "").strip()
    if isinstance(raw, list):
        raw = "".join(str(p) for p in raw)

    # Extrai JSON mesmo que o modelo adicione texto ao redor.
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
    """
    Regenera a resposta com system prompt endurecido usando ainvoke — não emite tokens
    para o cliente (evita vazar conteúdo bloqueado via on_chat_model_stream).
    """
    from assistente_medico_api.graph.nodes.retrieve import format_context_block

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
    """Registra evento de guardrail com JSON unificado (sem conteúdo completo)."""
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


# ---------------------------------------------------------------------------
# Nó principal
# ---------------------------------------------------------------------------


async def guardrail_node(state: ChatRAGState, settings: Settings) -> dict:
    """
    Nó assíncrono: classifica a resposta gerada e toma ação conforme veredicto.

    Fluxo:
    1. Tenta classificar via LLM; recorre a keywords se o LLM falhar.
    2. SEGURO  → passa sem alteração.
    3. AVISO   → appenda disclaimer ao answer.
    4. BLOQUEAR → tenta regenerar com prompt restritivo (1 tentativa);
                  se ainda bloqueado → substitui por mensagem padrão segura.
    """
    t0 = time.perf_counter()
    original_answer = state.get("answer") or ""
    patient_id_raw = state.get("patient_id") or ""
    patient_id = patient_id_raw or None
    query = state.get("query") or ""
    steps = list(state.get("reasoning_steps") or [])
    hist = list(state.get("chat_history") or [])

    def _elapsed_ms() -> float:
        return round((time.perf_counter() - t0) * 1000, 2)

    # --- Classificação: LLM com fallback determinístico ---
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

    # --- Ação conforme veredicto ---
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
        # --- BLOQUEAR: tenta regeneração com prompt mais restritivo ---
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

            # Verifica se a regeneração também seria bloqueada.
            try:
                regen_verdict, regen_reason = await _classify_with_llm(regen, settings)
            except Exception:
                blocked_kw, kw_r = _check_with_keywords(regen)
                regen_verdict = "BLOQUEAR" if blocked_kw else "SEGURO"
                regen_reason = kw_r or "classificação por keywords"

            if regen_verdict == "BLOQUEAR":
                guardrail_status = "blocked"
                final_answer = _SAFE_BLOCKED_MESSAGE
                steps.append("Guardrail: regeneração também bloqueada — mensagem padrão exibida.")
                _audit_guardrail(
                    event="guardrail_regen_blocked",
                    level=logging.WARNING,
                    patient_id=patient_id,
                    query=query,
                    answer=regen,
                    reason=regen_reason,
                    classifier_verdict=regen_verdict,
                    latency_ms=_elapsed_ms(),
                )
            else:
                guardrail_status = "regenerated"
                final_answer = regen
                steps.append("Guardrail: resposta substituída por versão regenerada mais segura.")
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

        except Exception as regen_exc:
            guardrail_status = "blocked"
            final_answer = _SAFE_BLOCKED_MESSAGE
            steps.append("Guardrail: regeneração falhou — mensagem padrão exibida.")
            _audit_guardrail(
                event="guardrail_regen_blocked",
                level=logging.WARNING,
                patient_id=patient_id,
                query=query,
                answer="",
                reason=str(regen_exc),
                classifier_verdict="BLOQUEAR",
                latency_ms=_elapsed_ms(),
            )

    # Atualiza histórico com a resposta final (pós-guardrail) para que turnos
    # futuros usem o conteúdo efetivamente entregue ao médico.
    if query:
        hist = hist + [
            {"role": "user", "content": query},
            {"role": "assistant", "content": final_answer},
        ]
        if len(hist) > CHAT_HISTORY_MAX_ITEMS:
            hist = hist[-CHAT_HISTORY_MAX_ITEMS:]

    audit_id = ""
    audit_payload = dict(state.get("rag_audit_payload") or {})
    if audit_payload:
        audit_payload["answer"] = final_answer
        audit_id = str(audit_payload.get("audit_id") or "")
        if getattr(settings, "rag_audit_enabled", True):
            try:
                append_audit_jsonl(audit_payload, resolve_runtime_path(settings.rag_audit_jsonl))
                steps.append(f"Auditoria RAG: interação registrada ({audit_id}).")
            except Exception as audit_exc:
                _logger.warning("rag_audit_write_failed; erro=%s", audit_exc)
                steps.append("Auditoria RAG: falha ao registrar, resposta preservada.")

    return {
        "answer": final_answer,
        "chat_history": hist,
        "audit_id": audit_id,
        "rag_audit_payload": audit_payload,
        "guardrail_status": guardrail_status,
        "guardrail_reason": reason,
        "reasoning_steps": steps,
    }
