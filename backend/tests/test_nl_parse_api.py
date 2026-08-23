"""API tests for the NL trade entry endpoint (POST /nl-parse)."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_list_models_includes_baseline(client):
    response = await client.get("/nl-parse/models")
    assert response.status_code == 200
    ids = {m["id"] for m in response.json()}
    assert "rule-based" in ids


async def test_parse_spot_text(client):
    response = await client.post(
        "/nl-parse",
        json={"text": "Buy 1 million euros against dollars, spot at 1.085", "model": "rule-based"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "rule-based"
    trade = body["trade"]
    assert trade["instrument_type"] == "SPOT"
    assert trade["currency_pair"] == "EURUSD"
    assert trade["direction"] == "BUY"
    assert trade["notional_1"] == 1_000_000
    assert trade["instrument_details"]["rate"] == 1.085


async def test_parse_resolves_market_rate_when_missing(client):
    with patch(
        "app.services.nl_parse.parser.get_rate",
        new=AsyncMock(return_value=(1.15, date(2026, 8, 19))),
    ):
        response = await client.post(
            "/nl-parse",
            json={"text": "Buy 1 million euros against dollars, spot", "model": "rule-based"},
        )
    assert response.status_code == 200
    assert response.json()["trade"]["instrument_details"]["rate"] == 1.15


async def test_parse_call_option(client):
    response = await client.post(
        "/nl-parse",
        json={
            "text": (
                "Buy a European call on EURUSD strike 1.10 expiring 2026-12-18, "
                "notional 500k, premium 25000 USD"
            ),
            "model": "rule-based",
        },
    )
    assert response.status_code == 200
    trade = response.json()["trade"]
    assert trade["instrument_type"] == "OPTION"
    details = trade["instrument_details"]
    assert details["option_type"] == "CALL"
    assert details["strike_rate"] == 1.10
    assert details["expiry_date"] == "2026-12-18"


async def test_parse_unknown_model_returns_400(client):
    response = await client.post(
        "/nl-parse", json={"text": "Buy EURUSD spot", "model": "does-not-exist"}
    )
    assert response.status_code == 400


async def test_parse_unparseable_returns_422(client):
    response = await client.post(
        "/nl-parse", json={"text": "please do something vague", "model": "rule-based"}
    )
    assert response.status_code == 422
