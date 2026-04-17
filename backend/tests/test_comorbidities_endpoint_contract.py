"""Tests for comorbidities endpoint contract."""

import pytest
from fastapi.testclient import TestClient

from assistente_medico_api.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.mark.asyncio
class TestComorbidititiesEndpointContract:
    """Test suite for GET /api/assistant/comorbidities endpoint."""

    def test_comorbidities_endpoint_returns_200(self, client):
        """Test that comorbidities endpoint returns 200 OK."""
        response = client.get("/api/assistant/comorbidities")
        assert response.status_code == 200

    def test_comorbidities_response_has_comorbidities_field(self, client):
        """Test that response contains comorbidities field."""
        response = client.get("/api/assistant/comorbidities")
        data = response.json()
        assert "comorbidities" in data

    def test_comorbidities_is_list(self, client):
        """Test that comorbidities is a list."""
        response = client.get("/api/assistant/comorbidities")
        data = response.json()
        assert isinstance(data["comorbidities"], list)

    def test_comorbidities_has_minimum_count(self, client):
        """Test that minimum comorbidities are present (original 6 + expanded)."""
        response = client.get("/api/assistant/comorbidities")
        data = response.json()
        # Original list had: HAS, DM2, IRC, DPOC, Obesidade, Outras
        # Expanded list should have at least those + pregnancy + others = 22+
        assert len(data["comorbidities"]) >= 6

    def test_comorbidity_option_has_required_fields(self, client):
        """Test that each comorbidity option has required fields."""
        response = client.get("/api/assistant/comorbidities")
        data = response.json()

        for comorbidity in data["comorbidities"]:
            assert "code" in comorbidity
            assert "label" in comorbidity
            assert "category" in comorbidity

    def test_comorbidity_fields_are_strings(self, client):
        """Test that comorbidity fields are strings."""
        response = client.get("/api/assistant/comorbidities")
        data = response.json()

        for comorbidity in data["comorbidities"]:
            assert isinstance(comorbidity["code"], str)
            assert isinstance(comorbidity["label"], str)
            assert isinstance(comorbidity["category"], str)

    def test_comorbidity_fields_not_empty(self, client):
        """Test that comorbidity fields are not empty."""
        response = client.get("/api/assistant/comorbidities")
        data = response.json()

        for comorbidity in data["comorbidities"]:
            assert len(comorbidity["code"]) > 0
            assert len(comorbidity["label"]) > 0
            assert len(comorbidity["category"]) > 0

    def test_original_comorbidities_present(self, client):
        """Test that original comorbidities are still present."""
        response = client.get("/api/assistant/comorbidities")
        data = response.json()
        codes = {c["code"] for c in data["comorbidities"]}

        # Original codes must be present
        original_codes = {"HAS", "DM2", "IRC", "DPOC", "Obesidade", "Outras"}
        assert original_codes.issubset(codes)

    def test_new_comorbidities_present(self, client):
        """Test that new comorbidities like pregnancy are present."""
        response = client.get("/api/assistant/comorbidities")
        data = response.json()
        codes = {c["code"] for c in data["comorbidities"]}

        # New codes added for expanded list
        assert "Gravidez" in codes
        assert "Puerperio" in codes

    def test_response_is_json(self, client):
        """Test that response is valid JSON."""
        response = client.get("/api/assistant/comorbidities")
        assert response.headers["content-type"].startswith("application/json")
