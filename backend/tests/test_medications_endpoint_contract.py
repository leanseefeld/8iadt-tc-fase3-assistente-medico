import pytest


@pytest.mark.asyncio
async def test_get_medications_contract(async_client):
    res = await async_client.get("/api/medications")
    assert res.status_code == 200

    payload = res.json()
    assert "medications" in payload
    assert isinstance(payload["medications"], list)
    assert len(payload["medications"]) > 0

    first = payload["medications"][0]
    assert {"code", "label", "activeIngredient", "sourceTags"}.issubset(first.keys())


@pytest.mark.asyncio
async def test_medications_contains_reference_items(async_client):
    res = await async_client.get("/api/medications")
    assert res.status_code == 200

    meds = res.json()["medications"]
    codes = {m["code"] for m in meds}

    assert "METFORMINA" in codes
    assert "LOSARTANA" in codes
    assert "ADALIMUMABE" in codes
