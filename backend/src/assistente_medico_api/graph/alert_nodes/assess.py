"""Decisão de alertas (LLM opcional + heurísticas) e preparação das cargas."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from assistente_medico_api.config import Settings
from assistente_medico_api.graph.clinical_alert_schemas import ClinicalAlertLlmAssessment
from assistente_medico_api.graph.clinical_alert_state import ClinicalAlertGraphState
from assistente_medico_api.graph.llm_client import build_llm, tracked_ainvoke


def _extract_first_json_object(raw: str) -> dict[str, Any]:
    """Extrai objeto JSON inicial de texto eventualmente rodeado por ruído."""
    start = raw.find("{")
    if start < 0:
        raise ValueError("Resposta não contém JSON objeto")
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(raw)):
        ch = raw[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                data = json.loads(raw[start : idx + 1])
                if not isinstance(data, dict):
                    raise ValueError("JSON raiz inválido")
                return data
    raise ValueError("JSON objeto incompleto")


def _fingerprint(parts: tuple[str, ...]) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x1e")
    return h.hexdigest()[:40]


async def node_assess_and_prepare_alerts(
    state: ClinicalAlertGraphState,
    *,
    settings: Settings,
) -> dict:
    """Combina vitais rápidos, contexto dos PCDTs e (opcional) LLM."""
    bundle = state.get("patient_bundle") or {}
    patient_id = str(state.get("patient_id") or "")
    trigger = state.get("trigger_type") or "check_in"
    interpreted = dict(state.get("interpreted") or {})

    assessments: list[dict] = []
    alert_payloads: list[dict] = []
    steps = list(state.get("reasoning_steps") or [])

    ref_txt = state.get("reference_docs_text") or ""
    pch_txt = state.get("patient_docs_text") or ""
    merged_context = (
        "--- Contexto PCDT (primeira recuperação) ---\n"
        f"{ref_txt}\n\n"
        "--- Contexto PCDT (segunda recuperação contextual) ---\n"
        f"{pch_txt}"
    )[:12000]

    # 1) Alertas rápidos de sinais vitais (mensagens já alinhadas ao legado da API).
    for msg in list(interpreted.get("vital_messages") or []):
        if not str(msg).strip():
            continue
        flags = interpreted.get("vital_flags") or []
        fingerprint = _fingerprint(
            ("vital_fast", patient_id, trigger, ",".join(sorted(flags)), msg)
        )
        alert_payloads.append(
            {
                "severity": "critical",
                "category": "clinical",
                "message": msg,
                "team": "doctors",
                "dedupe_key": fingerprint,
                "reason": {"kind": "vital_threshold"},
            }
        )

    # 2) Exame marcado como crítico pela equipe.
    if interpreted.get("exam_status_critical"):
        ename = str(interpreted.get("exam_name") or "Exame")
        eres = str(interpreted.get("exam_result") or "sem valor informado")
        msg = f"Resultado crítico registrado para {ename}: {eres}."
        fingerprint = _fingerprint(
            (
                "exam_critical",
                patient_id,
                str((state.get("exam_focus") or {}).get("id") or ""),
                eres.strip(),
            )
        )
        alert_payloads.append(
            {
                "severity": "critical",
                "category": "exam",
                "message": msg,
                "team": "doctors",
                "dedupe_key": fingerprint,
                "reason": {"kind": "exam_status_critical"},
            }
        )

    # 3) Avaliação via LLM (quando ligada) usando contexto recuperado dos PCDTs.
    llm_used = False
    if getattr(settings, "clinical_alerts_use_llm", True):
        system = (
            "Você é um médico moderador auxiliar para triagem institucional. "
            "Responda somente um JSON válido com os campos: "
            "`should_alert` (bool), `rationale` (string), "
            "`alerts` (lista de objetos com `severity`, `category`, "
            "`team`, `message`) e `confidence` (float 0-1).\n\n"
            "Regras: use apenas evidência presente nos trechos dos PCDT fornecidos; "
            "se o contexto for insuficiente, `should_alert` deve ser false; "
            "mensagens devem estar em pt-BR, curtas e acionáveis; "
            "evite repetir texto que apenas repita vitais já críticos se não há "
            "informação nova.\n\n"
            "Valor `team`: doctors | nursing | pharmacy | all."
        )
        human_blob = json.dumps(
            {
                "trigger": trigger,
                "paciente_resumo": {
                    "nome": bundle.get("name"),
                    "idade": bundle.get("age"),
                    "sexo": bundle.get("sex"),
                    "cid": bundle.get("cid_code"),
                    "rotulo_cid": bundle.get("cid_label"),
                    "sintomas": bundle.get("symptoms"),
                    "medicamentos": bundle.get("current_medications"),
                    "interpretado_locamente": interpreted,
                },
                "exame_focus": state.get("exam_focus"),
                "trechos_PCDT": merged_context,
            },
            ensure_ascii=False,
            default=str,
        )
        msgs = [
            SystemMessage(content=system),
            HumanMessage(content=human_blob),
        ]
        try:
            trace: list[Any] = []
            llm = build_llm(settings, temperature=0.0)
            result_msg = await tracked_ainvoke(
                llm,
                msgs,
                call_type="clinical_alert_assess",
                trace=trace,
                settings=settings,
            )
            raw = getattr(result_msg, "content", "") or ""
            if isinstance(raw, list):
                raw = "".join(str(p) for p in raw)
            data = _extract_first_json_object(str(raw))
            parsed = ClinicalAlertLlmAssessment.model_validate(data)
            llm_used = True
            assessments.append(
                {
                    "llm_should_alert": parsed.should_alert,
                    "confidence": parsed.confidence,
                    "rationale": parsed.rationale,
                    "trace": trace,
                }
            )
            if parsed.should_alert:
                seen_fp: set[str] = set()
                for idx, alert in enumerate(parsed.alerts):
                    sev = str(alert.get("severity") or "moderate").lower()
                    cat = str(alert.get("category") or "clinical").lower()
                    tm = str(alert.get("team") or "doctors").lower()
                    message = str(alert.get("message") or "").strip()
                    if not message:
                        continue
                    fingerprint = _fingerprint(
                        ("llm", patient_id, trigger, str(idx), message[:420])
                    )
                    if fingerprint in seen_fp:
                        continue
                    seen_fp.add(fingerprint)
                    alert_payloads.append(
                        {
                            "severity": sev,
                            "category": cat,
                            "message": message,
                            "team": tm if tm in {"doctors", "nursing", "pharmacy", "all"} else "doctors",
                            "dedupe_key": fingerprint,
                            "reason": {"kind": "llm_pcdt"},
                        }
                    )
        except Exception as exc:  # noqa: BLE001 - fallback controlado para demo
            steps.append(f"Avaliação LLM falhou ({type(exc).__name__}); usando heurísticas.")
            assessments.append({"llm_error": str(exc)[:300]})

    # 4) Heurísticas de check-in CID de sepse com sintomatologia sugestiva.
    if trigger == "check_in":
        cid_u = str(bundle.get("cid_code") or "").strip().upper()
        symptoms_l = str(bundle.get("symptoms") or "").lower()
        if cid_u == "A41.9" and any(
            s in symptoms_l for s in ("febre", "hipotermia", "taquipneia", "choque")
        ):
            msg = (
                "Possível cenário compatível com sepse (CID A41.9) com sintomas de alarme "
                '— correlacionar com PCDTs e revisar urgência segundo protocolo institucional.'
            )
            fp = _fingerprint(("cid_sepse_checkin", patient_id, cid_u, symptoms_l[:280]))
            alert_payloads.append(
                {
                    "severity": "critical",
                    "category": "clinical",
                    "message": msg,
                    "team": "doctors",
                    "dedupe_key": fp,
                    "reason": {"kind": "heuristic_check_in_sepsis"},
                }
            )

    # 5) Palavras de risco no corpus retornado mesmo sem LLM ligado ou sem alerta anterior.
    if interpreted.get("high_risk_keywords_in_context") and not any(
        p.get("reason", {}).get("kind") == "llm_pcdt" for p in alert_payloads
    ):
        msg = (
            "Trechos recuperados nos PCDTs mencionam gravidade/urgência relacionada ao caso "
            "- revisar recomendações institucionais e considerar intervenção prioritária."
        )
        fp = _fingerprint(("kw_risk_ctx", patient_id, trigger))
        alert_payloads.append(
            {
                "severity": "moderate",
                "category": "clinical",
                "message": msg,
                "team": "doctors",
                "dedupe_key": fp,
                "reason": {"kind": "keyword_risk_reference"},
            }
        )

    steps.append(
        f"Montagem final: llm_used={llm_used}, "
        f"alert_payloads_planejados={len(alert_payloads)}."
    )

    audit_trace = {
        "sources_reference": state.get("reference_sources") or [],
        "sources_patient_context": state.get("patient_sources") or [],
        "assessment_meta": assessments,
        "merged_context_chars": len(merged_context),
    }

    return {
        "assessments": assessments,
        "alert_payloads": alert_payloads,
        "audit_trace": audit_trace,
        "reasoning_steps": steps,
    }
