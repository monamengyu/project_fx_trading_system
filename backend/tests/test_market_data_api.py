from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.services.market_data.pairs import SUPPORTED_PAIRS


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_list_pairs_returns_all_supported_pairs(client):
    response = await client.get("/market-data/pairs")
    assert response.status_code == 200
    assert response.json() == {"pairs": SUPPORTED_PAIRS}


async def test_get_rate_success(client):
    with patch("app.api.routers.market_data.get_rate", new=AsyncMock(return_value=(1.0862, "2026-08-01"))):
        response = await client.get("/market-data/rates", params={"pair": "EURUSD"})
    assert response.status_code == 200
    assert response.json() == {"pair": "EURUSD", "rate": 1.0862, "as_of": "2026-08-01"}


async def test_get_rate_invalid_pair(client):
    response = await client.get("/market-data/rates", params={"pair": "XXXYYY"})
    assert response.status_code == 422


async def test_get_rate_upstream_failure(client):
    with patch("app.api.routers.market_data.get_rate", new=AsyncMock(side_effect=RuntimeError("boom"))):
        response = await client.get("/market-data/rates", params={"pair": "EURUSD"})
    assert response.status_code == 502
