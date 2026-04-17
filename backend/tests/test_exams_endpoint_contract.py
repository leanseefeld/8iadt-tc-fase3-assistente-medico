import pytest


def patient_create_payload() -> dict:
    return {
        "name": "Paciente Exames",
        "age": 55,
        "sex": "F",
        "cid": {"code": "L40.5", "label": "Artrite Psoriásica"},
    }


@pytest.mark.asyncio
async def test_create_and_patch_manual_exam(async_client):
    create_patient = await async_client.post("/api/patients", json=patient_create_payload())
    patient_id = create_patient.json()["patient"]["id"]

    created = await async_client.post(
        f"/api/patients/{patient_id}/exams",
        json={"name": "Urina tipo 1"},
    )
    assert created.status_code == 201
    exam = created.json()["exam"]
    assert exam["source"] == "manual"

    patched = await async_client.patch(
        f"/api/patients/{patient_id}/exams/{exam['id']}",
        json={"status": "completed", "result": "Normal"},
    )
    assert patched.status_code == 200
    assert patched.json()["exam"]["status"] == "completed"


@pytest.mark.asyncio
async def test_patch_critical_exam_creates_alert(async_client):
    create_patient = await async_client.post("/api/patients", json=patient_create_payload())
    patient_id = create_patient.json()["patient"]["id"]

    created_exam = await async_client.post(
        f"/api/patients/{patient_id}/exams",
        json={"name": "Lactato"},
    )
    exam_id = created_exam.json()["exam"]["id"]

    patched = await async_client.patch(
        f"/api/patients/{patient_id}/exams/{exam_id}",
        json={"status": "critical", "result": "5.8 mmol/L"},
    )
    assert patched.status_code == 200
    assert patched.json()["exam"]["status"] == "critical"

    alerts_res = await async_client.get(
        "/api/alerts",
        params={"patient_id": patient_id, "resolved": False},
    )
    assert alerts_res.status_code == 200
    alerts = alerts_res.json()["alerts"]
    assert any(a["category"] == "exam" and a["severity"] == "critical" for a in alerts)


@pytest.mark.asyncio
async def test_upload_manual_exam_file(async_client):
    create_patient = await async_client.post("/api/patients", json=patient_create_payload())
    patient_id = create_patient.json()["patient"]["id"]

    created = await async_client.post(
        f"/api/patients/{patient_id}/exams",
        json={"name": "Raio X"},
    )
    exam_id = created.json()["exam"]["id"]

    upload = await async_client.post(
        f"/api/patients/{patient_id}/exams/{exam_id}/upload",
        files={"file": ("laudo.txt", b"conteudo", "text/plain")},
    )
    assert upload.status_code == 200
    exam = upload.json()["exam"]
    assert exam["attachmentName"] == "laudo.txt"
    assert exam["attachmentMime"] == "text/plain"
    assert exam["attachmentSize"] == len(b"conteudo")
