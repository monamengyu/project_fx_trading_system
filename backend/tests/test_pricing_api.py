from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.pricing.option_pricer import price_option_quote

LIVE_RATE = 1.15


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _request(**overrides):
    payload = {
        "currency_pair": "EURUSD",
        "option_type": "CALL",
        "strike_rate": 1.15,
        "expiry_date": (date.today() + timedelta(days=120)).isoformat(),
        "notional_1": 1000000,
    }
    payload.update(overrides)
    return payload


def _expected(option_type: str, strike: float, notional: float, spot: float):
    priced = price_option_quote(
        option_type,
        spot=spot,
        strike_rate=strike,
        expiry_date=date.today() + timedelta(days=120),
        vol=0.10,
        valuation_date=date.today(),
    )
    return priced, round(notional * priced.premium, 2)


async def test_quote_call_in_quote_currency(client):
    with patch(
        "app.api.routers.pricing.get_rate",
        new=AsyncMock(return_value=(LIVE_RATE, "2026-08-16")),
    ):
        response = await client.post("/pricing/options", json=_request())

    assert response.status_code == 200
    body = response.json()
    assert body["currency_pair"] == "EURUSD"
    assert body["option_type"] == "CALL"
    assert body["premium_currency"] == "USD"
    assert body["spot"] == LIVE_RATE
    assert body["strike_rate"] == 1.15
    assert body["vol"] == 0.10

    priced, expected_total = _expected("CALL", 1.15, 1000000, LIVE_RATE)
    assert body["premium"] == priced.premium
    assert body["total_premium"] == expected_total
    assert body["greeks"]["delta"] == priced.greeks.delta


async def test_quote_usdjpy_premium_in_jpy(client):
    jpy_rate = 150.0
    payload = _request(currency_pair="USDJPY", option_type="PUT", strike_rate=150.0)
    with patch(
        "app.api.routers.pricing.get_rate",
        new=AsyncMock(return_value=(jpy_rate, "2026-08-16")),
    ):
        response = await client.post("/pricing/options", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["premium_currency"] == "JPY"
    assert body["total_premium"] is not None


async def test_quote_honours_requested_notional(client):
    with patch(
        "app.api.routers.pricing.get_rate",
        new=AsyncMock(return_value=(LIVE_RATE, "2026-08-16")),
    ):
        response = await client.post(
            "/pricing/options", json=_request(notional_1=500000)
        )

    assert response.status_code == 200
    _, expected_total = _expected("CALL", 1.15, 500000, LIVE_RATE)
    assert response.json()["total_premium"] == expected_total


async def test_quote_expired_option_rejected(client):
    payload = _request(expiry_date=(date.today() - timedelta(days=1)).isoformat())
    with patch(
        "app.api.routers.pricing.get_rate",
        new=AsyncMock(return_value=(LIVE_RATE, "2026-08-16")),
    ):
        response = await client.post("/pricing/options", json=payload)

    assert response.status_code == 422


async def test_quote_invalid_strike_rejected(client):
    payload = _request(strike_rate=0)
    with patch(
        "app.api.routers.pricing.get_rate",
        new=AsyncMock(return_value=(LIVE_RATE, "2026-08-16")),
    ):
        response = await client.post("/pricing/options", json=payload)

    assert response.status_code == 422


async def test_quote_upstream_unavailable(client):
    with patch(
        "app.api.routers.pricing.get_rate",
        new=AsyncMock(side_effect=RuntimeError("upstream down")),
    ):
        response = await client.post("/pricing/options", json=_request())

    assert response.status_code == 502
