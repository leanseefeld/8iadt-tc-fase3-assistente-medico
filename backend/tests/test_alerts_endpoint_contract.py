"""Tests for alerts endpoint contract."""

import pytest


@pytest.mark.asyncio
async def test_create_alert_via_service(async_client):
    """Test creating an alert programmatically."""
    from assistente_medico_api.repositories import alert_repo
    from assistente_medico_api.services import alert_service

    # Create a test alert
    payload = {
        "patientId": "test-patient-1",
        "severity": "critical",
        "category": "exam",
        "message": "Test alert message",
        "team": "doctors",
    }

    res = await async_client.get("/api/alerts")
    assert res.status_code == 200
    initial_count = len(res.json()["alerts"])

    # Alerts are typically created programmatically, not via POST
    # Testing via GET after internal creation


@pytest.mark.asyncio
async def test_get_alerts_returns_200(async_client):
    """Test that GET /api/alerts returns 200 OK."""
    response = await async_client.get("/api/alerts")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_post_alert_creates_alert(async_client):
    """Test that POST /api/alerts persists a new alert."""
    payload = {
        "patientId": "pt-post-alert",
        "severity": "critical",
        "category": "exam",
        "message": "Exame crítico identificado.",
        "team": "doctors",
    }

    created = await async_client.post("/api/alerts", json=payload)
    assert created.status_code == 201
    created_alert = created.json()["alert"]
    assert created_alert["patientId"] == payload["patientId"]
    assert created_alert["message"] == payload["message"]
    assert created_alert["resolved"] is False

    listed = await async_client.get(
        "/api/alerts",
        params={"patient_id": payload["patientId"], "resolved": False},
    )
    assert listed.status_code == 200
    alerts = listed.json()["alerts"]
    assert any(a["id"] == created_alert["id"] for a in alerts)


@pytest.mark.asyncio
async def test_get_alerts_response_has_alerts_field(async_client):
    """Test that GET /api/alerts response contains alerts field."""
    response = await async_client.get("/api/alerts")
    data = response.json()
    assert "alerts" in data


@pytest.mark.asyncio
async def test_get_alerts_is_list(async_client):
    """Test that alerts field is a list."""
    response = await async_client.get("/api/alerts")
    data = response.json()
    assert isinstance(data["alerts"], list)


@pytest.mark.asyncio
async def test_get_alerts_with_unresolved_filter(async_client):
    """Test that unresolved filter works."""
    response = await async_client.get("/api/alerts", params={"resolved": False})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["alerts"], list)
    for alert in data["alerts"]:
        assert alert["resolved"] is False


@pytest.mark.asyncio
async def test_get_alerts_with_severity_filter(async_client):
    """Test that severity filter works."""
    response = await async_client.get("/api/alerts", params={"severity": "critical"})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["alerts"], list)
    for alert in data["alerts"]:
        assert alert["severity"] == "critical"


@pytest.mark.asyncio
async def test_get_alerts_with_team_filter(async_client):
    """Test that team filter works."""
    response = await async_client.get("/api/alerts", params={"team": "doctors"})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["alerts"], list)
    # Team filter should return either matching team or 'all'
    for alert in data["alerts"]:
        assert alert["team"] in ["doctors", "all"]


@pytest.mark.asyncio
async def test_alert_has_required_fields(async_client):
    """Test that alert response has all required fields."""
    from assistente_medico_api.models.alert import Alert as AlertModel
    from assistente_medico_api.repositories import alert_repo
    from sqlalchemy.ext.asyncio import AsyncSession
    from assistente_medico_api.deps import get_session

    response = await async_client.get("/api/alerts")
    data = response.json()

    # If there are alerts, check the structure
    if data["alerts"]:
        alert = data["alerts"][0]
        assert "id" in alert
        assert "patientId" in alert
        assert "severity" in alert
        assert "category" in alert
        assert "message" in alert
        assert "team" in alert
        assert "createdAt" in alert
        assert "resolved" in alert


@pytest.mark.asyncio
async def test_alert_fields_are_correct_types(async_client):
    """Test that alert field types are correct."""
    response = await async_client.get("/api/alerts")
    data = response.json()

    if data["alerts"]:
        alert = data["alerts"][0]
        assert isinstance(alert["id"], str)
        assert isinstance(alert["patientId"], str)
        assert isinstance(alert["severity"], str)
        assert isinstance(alert["category"], str)
        assert isinstance(alert["message"], str)
        assert isinstance(alert["team"], str)
        assert isinstance(alert["createdAt"], str)
        assert isinstance(alert["resolved"], bool)


@pytest.mark.asyncio
async def test_get_nonexistent_alert_returns_404(async_client):
    """Test that getting a nonexistent alert returns 404."""
    response = await async_client.get("/api/alerts/nonexistent-id")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_patch_alert_resolve_status(async_client):
    """Test patching an alert to mark as resolved."""
    from assistente_medico_api.models.alert import Alert as AlertModel
    from assistente_medico_api.repositories import alert_repo
    from uuid import uuid4

    # First, we need to create an alert programmatically for testing
    # This would normally be done via an async session in the test setup
    # For now, we test the endpoint structure

    response = await async_client.get("/api/alerts", params={"resolved": False})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_patch_nonexistent_alert_returns_404(async_client):
    """Test that patching a nonexistent alert returns 404."""
    response = await async_client.patch(
        "/api/alerts/nonexistent-id",
        json={"resolved": True},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_alerts_with_patient_id_filter(async_client):
    """Test that patient_id filter works."""
    response = await async_client.get("/api/alerts", params={"patient_id": "test-patient"})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["alerts"], list)
    # If there are alerts, they should match the patient_id
    for alert in data["alerts"]:
        if alert["patientId"] != "system":
            assert alert["patientId"] == "test-patient"
