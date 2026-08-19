from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.trade import Trade
from app.models.trade_state import TradeStateLog
from app.services.business_calendar import add_business_days, spot_value_date


@pytest.fixture
async def client():
    created_ids = []
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.created_trade_ids = created_ids
        yield ac
    if created_ids:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(TradeStateLog).where(TradeStateLog.trade_id.in_(created_ids))
            )
            await session.execute(delete(Trade).where(Trade.trade_id.in_(created_ids)))
            await session.commit()


TODAY = date.today()
SPOT_VALUE = spot_value_date(TODAY)


def _payload(instrument_type, settlement):
    return {
        "instrument_type": instrument_type,
        "currency_pair": "EURUSD",
        "direction": "BUY",
        "currency_1": "EUR",
        "notional_1": 1000000,
        "currency_2": "USD",
        "counterparty": "BANK_A",
        "instrument_details": {
            "instrument_type": instrument_type,
            "rate": 1.085,
            "settlement_date": settlement.isoformat(),
        },
    }


async def test_spot_settlement_at_spot_value_date_ok(client):
    r = await client.post("/trades", json=_payload("SPOT", SPOT_VALUE))
    assert r.status_code == 201
    client.created_trade_ids.append(r.json()["trade_id"])


async def test_spot_settlement_beyond_window_rejected(client):
    r = await client.post("/trades", json=_payload("SPOT", add_business_days(TODAY, 3)))
    assert r.status_code == 422


async def test_spot_settlement_in_past_rejected(client):
    r = await client.post("/trades", json=_payload("SPOT", TODAY - timedelta(days=1)))
    assert r.status_code == 422


async def test_forward_settlement_at_spot_value_date_rejected(client):
    r = await client.post("/trades", json=_payload("FORWARD", SPOT_VALUE))
    assert r.status_code == 422


async def test_forward_settlement_beyond_window_ok(client):
    r = await client.post("/trades", json=_payload("FORWARD", add_business_days(TODAY, 5)))
    assert r.status_code == 201
    client.created_trade_ids.append(r.json()["trade_id"])


def _next_saturday(start):
    d = start
    while True:
        d += timedelta(days=1)
        if d.weekday() == 5:  # Saturday
            return d


async def test_spot_settlement_on_weekend_rejected(client):
    r = await client.post("/trades", json=_payload("SPOT", _next_saturday(TODAY)))
    assert r.status_code == 422


async def test_forward_settlement_on_weekend_rejected(client):
    # a weekend well beyond the spot window: passes the window rule, fails the
    # business-day rule
    settlement = _next_saturday(spot_value_date(TODAY))
    r = await client.post("/trades", json=_payload("FORWARD", settlement))
    assert r.status_code == 422
