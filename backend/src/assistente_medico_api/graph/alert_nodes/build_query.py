"""Montagem de consultas iniciais e aprofundadas para recuperação nos PCDTs."""

from __future__ import annotations

from assistente_medico_api.graph.clinical_alert_state import ClinicalAlertGraphState
from assistente_medico_api.graph.nodes.patient_context import format_gender_label, format_sex_label, resolve_comorbidity_labels


def _format_medications(meds: object) -> str:
    if isinstance(meds, list):
        return ", ".join(str(m) for m in meds if str(m).strip())
    return str(meds or "").strip()


def node_build_queries(state: ClinicalAlertGraphState) -> dict:
    """Define `initial_query` e `deep_query` conforme gatilho clínico."""
    bundle = state.get("patient_bundle") or {}
    trigger = state.get("trigger_type") or "check_in"

    cid_code = str(bundle.get("cid_code") or "").strip()
    cid_label = str(bundle.get("cid_label") or "").strip()
    age = bundle.get("age")
    sex = format_sex_label(str(bundle.get("sex") or ""))
    gender = format_gender_label(bundle.get("gender"))
    symptoms = str(bundle.get("symptoms") or "").strip()
    comorb_codes = bundle.get("comorbidities") or []
    comorb = resolve_comorbidity_labels(list(comorb_codes) if isinstance(comorb_codes, list) else [])
    meds_txt = _format_medications(bundle.get("current_medications"))

    demographic = f"Idade {age} anos; sexo biológico {sex}"
    if gender:
        demographic += f"; identidade de gênero {gender}"
    if comorb:
        demographic += f"; comorbidades {', '.join(comorb)}"

    steps = list(state.get("reasoning_steps") or [])

    if trigger == "check_in":
        initial = (
            f"PCDT diretriz condição crítica encaminhamento urgência "
            f"CID-10 {cid_code} {cid_label}. "
            f"{demographic}. "
            f"Sintomas relatados: {symptoms or '—'}. "
            f"Medicamentos em uso: {meds_txt or '—'}. "
            f"Critérios de gravidade e monitoramento."
        )
        deep = (
            f"Estratificação de risco PCDT para paciente {demographic} com diagnóstico "
            f"{cid_code} {cid_label}. "
            f"Sintomas: {symptoms or '—'}. "
            f"Medicamentos: {meds_txt or '—'}. "
            f"Interações, contraindicações e sinais de alarme."
        )
        steps.append("Consulta inicial de check-in montada (condição + sintomas + medicamentos).")
    elif trigger == "exam_result":
        focus = state.get("exam_focus") or {}
        ename = str(focus.get("name") or "").strip()
        eres = str(focus.get("result") or "").strip()
        einterp = str(focus.get("interpretation") or "").strip()
        est = str(focus.get("status") or "").strip()
        initial = (
            f"PCDT exame laboratorial {ename} valores de referência interpretação "
            f"resultado {eres or '—'} status {est}. "
            f"Doença guia {cid_code} {cid_label}."
        )
        deep = (
            f"PCDT {cid_code} {cid_label}: risco clínico considerando exame {ename} "
            f"com resultado {eres or '—'} e interpretação {einterp or '—'}; "
            f"{demographic}; medicamentos {meds_txt or '—'}; sintomas {symptoms or '—'}."
        )
        steps.append("Consulta orientada a exame e valores de referência montada.")
    else:  # vital_sign
        vitals = state.get("latest_vitals") or {}
        spo2 = vitals.get("oxygen_saturation")
        temp = vitals.get("temperature")
        fc = vitals.get("heart_rate")
        pa = vitals.get("blood_pressure")
        initial = (
            "PCDT sinais vitais instabilidade sepse choque sepse deterioração "
            f"CID-10 {cid_code} {cid_label}; SpO2 {spo2}%; temperatura {temp} °C; "
            f"FC {fc} bpm; PA {pa}."
        )
        deep = (
            f"Manejo e alertas segundo PCDT para paciente com {demographic} "
            f"e CID {cid_code}: contexto vitais Críticos possíveis (hipóxia, febre, "
            f"taquicardia, hipertensão)."
        )
        steps.append("Consulta orientada a sinais vitais montada.")

    return {"initial_query": initial, "deep_query": deep, "reasoning_steps": steps}
