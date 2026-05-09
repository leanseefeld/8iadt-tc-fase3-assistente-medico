"""Tests for prescriptions endpoint contract."""

import pytest

from tests.test_patients_endpoint_contract import patient_create_payload


def _prescription_body() -> dict:
    return {
        "prescriberKind": "doctor",
        "prescriberName": "Dra. Ana Souza",
        "prescriberCrm": "123456",
        "prescriberCrmUf": "SP",
        "institutionName": "Hospital Exemplo",
        "institutionCnpjCnes": "00000000000191",
        "institutionAddress": "Rua Exemplo, 100 — São Paulo/SP",
        "institutionPhone": "(11) 3000-0000",
        "patientCpf": "12345678909",
        "items": [
            {
                "medicationName": "Amoxicilina",
                "concentration": "500 mg",
                "pharmaceuticalForm": "Cápsula",
                "quantity": "21",
                "posology": "1 cápsula de 8 em 8 horas por 7 dias",
            },
        ],
        "notes": "Observação de teste",
    }


@pytest.mark.asyncio
async def test_create_prescription_201(async_client):
    created = await async_client.post("/api/patients", json=patient_create_payload())
    assert created.status_code == 201
    pid = created.json()["patient"]["id"]

    res = await async_client.post(
        f"/api/patients/{pid}/prescriptions",
        json=_prescription_body(),
    )
    assert res.status_code == 201
    p = res.json()["prescription"]
    assert p["id"].startswith("px-")
    assert p["patientId"] == pid
    assert p["prescriberKind"] == "doctor"
    assert len(p["items"]) == 1
    assert p["items"][0]["medicationName"] == "Amoxicilina"
    assert p["archivedAt"] is None


@pytest.mark.asyncio
async def test_list_prescriptions_excludes_archived_by_default(async_client):
    created = await async_client.post("/api/patients", json=patient_create_payload())
    pid = created.json()["patient"]["id"]
    await async_client.post(f"/api/patients/{pid}/prescriptions", json=_prescription_body())

    listed = await async_client.get(f"/api/patients/{pid}/prescriptions")
    assert listed.status_code == 200
    assert len(listed.json()["prescriptions"]) == 1


@pytest.mark.asyncio
async def test_archive_prescription_soft_delete(async_client):
    created = await async_client.post("/api/patients", json=patient_create_payload())
    pid = created.json()["patient"]["id"]
    rx = await async_client.post(
        f"/api/patients/{pid}/prescriptions",
        json=_prescription_body(),
    )
    rid = rx.json()["prescription"]["id"]

    arch = await async_client.patch(
        f"/api/prescriptions/{rid}/archive",
        json={"reason": "Erro de digitação no nome do medicamento.", "archivedBy": "Dra. Ana Souza"},
    )
    assert arch.status_code == 200
    p = arch.json()["prescription"]
    assert p["archivedAt"] is not None
    assert p["archivedReason"] is not None
    assert p["archivedBy"] == "Dra. Ana Souza"

    active_list = await async_client.get(f"/api/patients/{pid}/prescriptions")
    assert active_list.json()["prescriptions"] == []

    all_list = await async_client.get(
        f"/api/patients/{pid}/prescriptions",
        params={"includeArchived": True},
    )
    assert len(all_list.json()["prescriptions"]) == 1


@pytest.mark.asyncio
async def test_archive_requires_reason_min_length(async_client):
    created = await async_client.post("/api/patients", json=patient_create_payload())
    pid = created.json()["patient"]["id"]
    rx = await async_client.post(
        f"/api/patients/{pid}/prescriptions",
        json=_prescription_body(),
    )
    rid = rx.json()["prescription"]["id"]

    bad = await async_client.patch(
        f"/api/prescriptions/{rid}/archive",
        json={"reason": "curt", "archivedBy": "Dr. X"},
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_doctor_requires_crm(async_client):
    created = await async_client.post("/api/patients", json=patient_create_payload())
    pid = created.json()["patient"]["id"]
    body = _prescription_body()
    body["prescriberCrm"] = ""
    res = await async_client.post(f"/api/patients/{pid}/prescriptions", json=body)
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_ai_assistant_allows_empty_crm(async_client):
    created = await async_client.post("/api/patients", json=patient_create_payload())
    pid = created.json()["patient"]["id"]
    body = _prescription_body()
    body["prescriberKind"] = "ai_assistant"
    body["prescriberName"] = "Assistente Médico IA"
    body["prescriberCrm"] = ""
    body["prescriberCrmUf"] = ""
    res = await async_client.post(f"/api/patients/{pid}/prescriptions", json=body)
    assert res.status_code == 201
    assert res.json()["prescription"]["prescriberKind"] == "ai_assistant"


@pytest.mark.asyncio
async def test_get_prescription_by_id(async_client):
    created = await async_client.post("/api/patients", json=patient_create_payload())
    pid = created.json()["patient"]["id"]
    rx = await async_client.post(f"/api/patients/{pid}/prescriptions", json=_prescription_body())
    rid = rx.json()["prescription"]["id"]
    got = await async_client.get(f"/api/prescriptions/{rid}")
    assert got.status_code == 200
    assert got.json()["prescription"]["id"] == rid


@pytest.mark.asyncio
async def test_list_unknown_patient_404(async_client):
    res = await async_client.get("/api/patients/pt-inexistente/prescriptions")
    assert res.status_code == 404
