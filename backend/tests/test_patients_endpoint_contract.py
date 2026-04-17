import pytest


def patient_create_payload() -> dict:
    return {
        "name": "Paciente Teste",
        "age": 60,
        "sex": "M",
        "cid": {"code": "A41.9", "label": "Sepse não especificada"},
        "observations": "Observacao inicial",
        "comorbidities": ["HAS"],
        "currentMedications": "Losartana",
    }


@pytest.mark.asyncio
async def test_create_and_get_patient(async_client):
    create = await async_client.post("/api/patients", json=patient_create_payload())
    assert create.status_code == 201
    data = create.json()["patient"]
    assert data["id"].startswith("pt-")
    assert data["cid"]["code"] == "A41.9"
    assert len(data["exams"]) >= 1

    got = await async_client.get(f"/api/patients/{data['id']}")
    assert got.status_code == 200
    assert got.json()["patient"]["id"] == data["id"]


@pytest.mark.asyncio
async def test_list_patients_with_filters(async_client):
    await async_client.post("/api/patients", json=patient_create_payload())
    res = await async_client.get("/api/patients", params={"status": "admitted", "q": "Paciente"})
    assert res.status_code == 200
    payload = res.json()
    assert "patients" in payload
    assert len(payload["patients"]) >= 1


@pytest.mark.asyncio
async def test_patch_vitals_keeps_latest(async_client):
    create = await async_client.post("/api/patients", json=patient_create_payload())
    patient_id = create.json()["patient"]["id"]

    r1 = await async_client.patch(
        f"/api/patients/{patient_id}/vitals",
        json={"oxygenSaturation": 95, "heartRate": 80},
    )
    assert r1.status_code == 200

    r2 = await async_client.patch(
        f"/api/patients/{patient_id}/vitals",
        json={"oxygenSaturation": 90},
    )
    assert r2.status_code == 200
    latest = r2.json()["patient"]["vitalSigns"]
    assert latest["oxygenSaturation"] == 90
    assert latest["heartRate"] == 80


@pytest.mark.asyncio
async def test_patch_vitals_critical_creates_alert(async_client):
    create = await async_client.post("/api/patients", json=patient_create_payload())
    patient_id = create.json()["patient"]["id"]

    patched = await async_client.patch(
        f"/api/patients/{patient_id}/vitals",
        json={"oxygenSaturation": 89},
    )
    assert patched.status_code == 200

    alerts = await async_client.get(
        "/api/alerts",
        params={"patient_id": patient_id, "resolved": False},
    )
    assert alerts.status_code == 200
    items = alerts.json()["alerts"]
    assert any(
        a["severity"] == "critical"
        and a["category"] == "clinical"
        and "SpO2 crítico" in a["message"]
        for a in items
    )


@pytest.mark.asyncio
async def test_patch_vitals_bp_shorthand_creates_alert(async_client):
    create = await async_client.post("/api/patients", json=patient_create_payload())
    patient_id = create.json()["patient"]["id"]

    patched = await async_client.patch(
        f"/api/patients/{patient_id}/vitals",
        json={"bloodPressure": "19/11"},
    )
    assert patched.status_code == 200

    alerts = await async_client.get(
        "/api/alerts",
        params={"patient_id": patient_id, "resolved": False},
    )
    assert alerts.status_code == 200
    items = alerts.json()["alerts"]
    assert any(
        a["severity"] == "critical"
        and a["category"] == "clinical"
        and "Pressão arterial crítica" in a["message"]
        for a in items
    )


@pytest.mark.asyncio
async def test_readmit_returns_409_for_already_admitted(async_client):
    create = await async_client.post("/api/patients", json=patient_create_payload())
    patient_id = create.json()["patient"]["id"]
    res = await async_client.post(f"/api/patients/{patient_id}/readmit")
    assert res.status_code == 409
