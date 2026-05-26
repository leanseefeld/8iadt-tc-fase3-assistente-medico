"""Testes smoke do grafo LangGraph de alertas clínicos (sem vetorstore)."""

import pytest


@pytest.mark.asyncio
async def test_clinical_alert_graph_vital_critical_without_store():
    from assistente_medico_api.config import Settings
    from assistente_medico_api.graph.clinical_alerts import build_compiled_clinical_alert_graph, seed_run_state

    graph = build_compiled_clinical_alert_graph(None, Settings())
    state = seed_run_state(
        patient_id="px",
        trigger_type="vital_sign",
        patient_bundle={
            "name": "Teste Grafo",
            "age": 70,
            "sex": "F",
            "gender": None,
            "symptoms": "",
            "comorbidities": [],
            "current_medications": [],
            "cid_code": "R50.9",
            "cid_label": "Febre não especificada",
        },
        latest_vitals={
            "blood_pressure": "120/80",
            "temperature": 36.5,
            "oxygen_saturation": 87,
            "heart_rate": 80,
            "recorded_at": None,
        },
    )
    cfg = {}
    final = await graph.ainvoke(state, cfg)
    messages = [p.get("message", "") for p in final.get("alert_payloads") or []]
    assert any("SpO2 crítico" in m for m in messages), messages
