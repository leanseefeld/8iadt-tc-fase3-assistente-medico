import pytest


def patient_create_payload() -> dict:
    return {
        "name": "Paciente Fluxo",
        "age": 62,
        "sex": "M",
        "cid": {"code": "A41.9", "label": "Sepse nao especificada"},
        "observations": "Observacao inicial",
        "comorbidities": ["HAS"],
        "currentMedications": "Losartana",
    }


@pytest.mark.asyncio
async def test_post_decision_flow_returns_lines_and_meta(async_client):
    created = await async_client.post("/api/patients", json=patient_create_payload())
    assert created.status_code == 201
    patient_id = created.json()["patient"]["id"]

    res = await async_client.post(
        "/api/assistant/decision-flow",
        json={"patientId": patient_id},
    )

    assert res.status_code == 200
    payload = res.json()
    assert isinstance(payload["lines"], list)
    assert len(payload["lines"]) >= 5
    assert any("Triagem" in line for line in payload["lines"])
    assert payload["meta"]["sepsisCritical"] is True
    assert payload["meta"]["pharmacyInteraction"] is False


@pytest.mark.asyncio
async def test_post_decision_flow_returns_404_for_unknown_patient(async_client):
    res = await async_client.post(
        "/api/assistant/decision-flow",
        json={"patientId": "pt-missing"},
    )

    assert res.status_code == 404
    assert "detail" in res.json()
