"""Interpretação de sinais locais antes da segunda recuperação aos PCDTs."""

from __future__ import annotations

from assistente_medico_api.graph.clinical_alert_state import ClinicalAlertGraphState


def _extract_systolic(value: str | None) -> int | None:
    if not value:
        return None
    left = str(value).split("/")[0].strip()
    if not left:
        return None
    try:
        systolic = int(left)
        if systolic <= 30:
            return systolic * 10
        return systolic
    except ValueError:
        return None


def node_interpret_local(state: ClinicalAlertGraphState) -> dict:
    """Marca achados rápidos (vitais, exame marcado como crítico) para próximos nós."""
    trigger = state.get("trigger_type")
    interpreted: dict = {
        "vital_flags": [],
        "vital_messages": [],
        "exam_status_critical": False,
        "exam_name": "",
        "exam_result": "",
        "exam_interpretation": "",
        "high_risk_keywords_in_context": False,
    }
    steps = list(state.get("reasoning_steps") or [])

    if trigger == "vital_sign":
        vitals = state.get("latest_vitals") or {}
        bp = vitals.get("blood_pressure")
        spo2 = vitals.get("oxygen_saturation")
        temp = vitals.get("temperature")
        hr = vitals.get("heart_rate")

        if spo2 is not None and spo2 < 92:
            interpreted["vital_flags"].append("oxigenacao")
            interpreted["vital_messages"].append(
                f"SpO2 crítico registrado ({spo2}%)."
            )
        if temp is not None and (temp >= 39 or temp < 35):
            interpreted["vital_flags"].append("temperatura")
            interpreted["vital_messages"].append(
                f"Temperatura crítica registrada ({temp:.1f} °C)."
            )
        if hr is not None and (hr > 120 or hr < 45):
            interpreted["vital_flags"].append("frequencia_cardiaca")
            interpreted["vital_messages"].append(
                f"Frequência cardíaca crítica registrada ({hr} bpm)."
            )
        if bp is not None:
            syst = _extract_systolic(str(bp))
            if syst is not None and syst >= 180:
                interpreted["vital_flags"].append("pressao_arterial")
                interpreted["vital_messages"].append(
                    f"Pressão arterial crítica registrada ({bp})."
                )
        steps.append(
            "Interpretação local: sinais vitais avaliados com limiares de alerta rápido."
        )

    elif trigger == "exam_result":
        focus = state.get("exam_focus") or {}
        interpreted["exam_name"] = str(focus.get("name") or "")
        interpreted["exam_result"] = str(focus.get("result") or "")
        interpreted["exam_interpretation"] = str(focus.get("interpretation") or "")
        interpreted["exam_status_critical"] = str(focus.get("status") or "") == "critical"
        steps.append(
            "Interpretação local: foco em resultado de exame e status definido pela equipe."
        )

    bundle = state.get("patient_bundle") or {}
    if str(bundle.get("cid_code") or "").strip().upper() == "A41.9":
        steps.append(
            "Interpretação local: CID A41.9 (sepse) — considerada condição potencialmente grave."
        )

    merged_ctx = (
        (state.get("reference_docs_text") or "")
        .lower()
    )
    for token in ("urgência", "urgente", "gravíssimo", "grave", "imediato"):
        if token in merged_ctx:
            interpreted["high_risk_keywords_in_context"] = True
            break

    steps.append("Interpretação local concluída.")
    return {"interpreted": interpreted, "reasoning_steps": steps}
