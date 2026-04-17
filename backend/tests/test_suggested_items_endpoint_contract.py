import pytest


@pytest.mark.asyncio
async def test_create_and_patch_suggested_item(async_client):
    create_patient = await async_client.post(
        "/api/patients",
        json={
            "name": "Paciente Ação",
            "age": 48,
            "sex": "M",
            "cid": {"code": "E11.9", "label": "Diabetes Mellitus tipo 2 sem complicações"},
        },
    )
    patient_id = create_patient.json()["patient"]["id"]

    created = await async_client.post(
        f"/api/patients/{patient_id}/suggested-items",
        json={"type": "review", "description": "Avaliar em 24h"},
    )
    assert created.status_code == 201
    item = created.json()["item"]
    assert item["status"] == "suggested"

    patched = await async_client.patch(
        f"/api/patients/{patient_id}/suggested-items/{item['id']}",
        json={"status": "accepted", "description": "Avaliar em 12h"},
    )
    assert patched.status_code == 200
    payload = patched.json()["item"]
    assert payload["status"] == "accepted"
    assert payload["description"] == "Avaliar em 12h"
