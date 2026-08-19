from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.trade import Trade
from app.models.trade_state import TradeStateLog
from app.services.business_calendar import add_business_days


@pytest.fixture
async def client():
    created_ids = []
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.created_trade_ids = created_ids
        yield ac
    if created_ids:
        async with AsyncSessionLocal() as session:
            # delete lifecycle rows first: the FK has no ON DELETE CASCADE
            await session.execute(
                delete(TradeStateLog).where(TradeStateLog.trade_id.in_(created_ids))
            )
            await session.execute(delete(Trade).where(Trade.trade_id.in_(created_ids)))
            await session.commit()


FORWARD_PAYLOAD = {
    "instrument_type": "FORWARD",
    "currency_pair": "EURUSD",
    "direction": "BUY",
    "currency_1": "EUR",
    "notional_1": 1000000,
    "currency_2": "USD",
    "notional_2": 1092000,
    "counterparty": "BANK_A",
    "instrument_details": {
        "instrument_type": "FORWARD",
        "rate": 1.092,
        "settlement_date": add_business_days(date.today(), 20).isoformat(),
    },
}


async def test_forward_booking_success(client):
    response = await client.post("/trades", json=FORWARD_PAYLOAD)
    assert response.status_code == 201
    body = response.json()
    assert body["instrument_type"] == "FORWARD"
    assert body["status"] == "PENDING_CONFIRMATION"
    assert body["instrument_details"]["instrument_type"] == "FORWARD"
    assert body["instrument_details"]["rate"] == 1.092
    assert (
        body["instrument_details"]["settlement_date"]
        == FORWARD_PAYLOAD["instrument_details"]["settlement_date"]
    )
    client.created_trade_ids.append(body["trade_id"])


async def test_forward_booking_persists(client):
    created = await client.post("/trades", json=FORWARD_PAYLOAD)
    assert created.status_code == 201
    trade_id = created.json()["trade_id"]
    client.created_trade_ids.append(trade_id)

    fetched = await client.get(f"/trades/{trade_id}")
    assert fetched.status_code == 200
    details = fetched.json()["instrument_details"]
    assert details["instrument_type"] == "FORWARD"
    assert details["rate"] == 1.092
    assert details["settlement_date"] == FORWARD_PAYLOAD["instrument_details"]["settlement_date"]


async def test_forward_booking_writes_initial_state_log(client):
    created = await client.post("/trades", json=FORWARD_PAYLOAD)
    assert created.status_code == 201
    trade_id = created.json()["trade_id"]
    client.created_trade_ids.append(trade_id)

    history = await client.get(f"/trades/{trade_id}/history")
    assert history.status_code == 200
    entries = history.json()["history"]
    assert len(entries) == 1
    assert entries[0]["state"] == "PENDING_CONFIRMATION"


async def test_forward_mismatched_instrument_details_fails(client):
    bad_payload = {
        **FORWARD_PAYLOAD,
        "instrument_details": {
            "instrument_type": "OPTION",
            "option_type": "CALL",
            "strike_rate": 1.09,
            "premium_date": "2026-07-30",
            "expiry_date": "2026-09-15",
            "delivery_date": "2026-09-17",
            "premium": 12500,
            "premium_currency": "USD",
            "exercise_style": "EUROPEAN",
        },
    }
    response = await client.post("/trades", json=bad_payload)
    assert response.status_code == 422
