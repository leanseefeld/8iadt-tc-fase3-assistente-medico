"""Deduplicação de alertas de sinais vitais idênticos."""

import pytest


@pytest.mark.asyncio
async def test_duplicate_identical_critical_vital_not_duplicated_async_client(async_client):
    create = await async_client.post(
        "/api/patients",
        json={
            "name": "Dedupe Vitals",
            "age": 51,
            "sex": "M",
            "cid": {"code": "Z00.0", "label": "Exame geral"},
        },
    )
    assert create.status_code == 201
    pid = create.json()["patient"]["id"]
    await async_client.patch(f"/api/patients/{pid}/vitals", json={"oxygenSaturation": 88})
    await async_client.patch(f"/api/patients/{pid}/vitals", json={"oxygenSaturation": 88})
    alerts = await async_client.get(
        "/api/alerts",
        params={"patient_id": pid, "resolved": False},
    )
    spo2_critical = [
        a
        for a in alerts.json()["alerts"]
        if "SpO2 crítico" in a["message"]
    ]
    assert len(spo2_critical) == 1
