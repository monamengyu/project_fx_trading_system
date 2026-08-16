import uuid

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete

from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.enums import TradeState
from app.models.trade import Trade
from app.models.trade_state import TradeStateLog
from app.services.trade_lifecycle import append_state


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


SPOT_PAYLOAD = {
    "instrument_type": "SPOT",
    "currency_pair": "EURUSD",
    "direction": "BUY",
    "currency_1": "EUR",
    "notional_1": 1000000,
    "currency_2": "USD",
    "counterparty": "BANK_A",
    "instrument_details": {
        "instrument_type": "SPOT",
        "rate": 1.085,
        "settlement_date": "2026-08-01",
    },
}


async def _book_trade(client, payload=SPOT_PAYLOAD):
    response = await client.post("/trades", json=payload)
    if response.status_code == 201:
        client.created_trade_ids.append(response.json()["trade_id"])
    return response


async def test_booking_writes_initial_state_log(client):
    created = await _book_trade(client)
    assert created.status_code == 201
    trade_id = created.json()["trade_id"]

    history = await client.get(f"/trades/{trade_id}/history")
    assert history.status_code == 200
    body = history.json()
    assert body["trade_id"] == trade_id
    assert len(body["history"]) == 1
    entry = body["history"][0]
    assert entry["state"] == "PENDING_CONFIRMATION"
    assert entry["changed_by"] == "system"


async def test_history_is_append_only_and_ordered(client):
    created = await _book_trade(client)
    assert created.status_code == 201
    trade_id = uuid.UUID(created.json()["trade_id"])

    async with AsyncSessionLocal() as session:
        await append_state(
            session, trade_id, TradeState.BOOKED, changed_by="operator", notes="confirmed"
        )
        await append_state(
            session, trade_id, TradeState.AMENDED, changed_by="operator", notes="new rate"
        )
        await session.commit()

    history = await client.get(f"/trades/{trade_id}/history")
    assert history.status_code == 200
    body = history.json()
    states = [entry["state"] for entry in body["history"]]
    assert states == ["PENDING_CONFIRMATION", "BOOKED", "AMENDED"]
    assert body["history"][1]["changed_by"] == "operator"
    assert body["history"][1]["notes"] == "confirmed"


async def test_history_timestamps_are_utc_z(client):
    created = await _book_trade(client)
    trade_id = created.json()["trade_id"]

    history = await client.get(f"/trades/{trade_id}/history")
    changed_at = history.json()["history"][0]["changed_at"]
    assert changed_at.endswith("Z")


async def test_history_404_for_unknown_trade(client):
    response = await client.get("/trades/00000000-0000-0000-0000-000000000000/history")
    assert response.status_code == 404
