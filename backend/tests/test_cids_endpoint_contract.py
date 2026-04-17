import pytest


@pytest.mark.asyncio
async def test_get_cids_contract(async_client):
    res = await async_client.get("/api/cids")
    assert res.status_code == 200
    payload = res.json()
    assert "cids" in payload
    assert isinstance(payload["cids"], list)
    assert len(payload["cids"]) > 0
    assert {"code", "label"}.issubset(payload["cids"][0].keys())
