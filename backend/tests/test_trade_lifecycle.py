import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.enums import TradeState, TradeStatus
from app.models.trade import Trade
from app.models.trade_state import TradeStateLog
from app.services import trade_lifecycle
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
        "settlement_date": spot_value_date(date.today()).isoformat(),
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
        await trade_lifecycle.append_state(
            session, trade_id, TradeState.BOOKED, changed_by="operator", notes="confirmed"
        )
        await trade_lifecycle.append_state(
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


# --- cancel / amend ---------------------------------------------------------


async def _confirm_trade(trade_id: uuid.UUID) -> None:
    """Simulate the confirmation step: BOOKED status + BOOKED log entry."""
    async with AsyncSessionLocal() as session:
        trade = await session.get(Trade, trade_id)
        trade.status = TradeStatus.BOOKED
        await trade_lifecycle.append_state(
            session, trade_id, TradeState.BOOKED, changed_by="operator"
        )
        await session.commit()


async def test_cancel_pending_trade(client):
    created = await _book_trade(client)
    assert created.status_code == 201
    trade_id = created.json()["trade_id"]

    response = await client.post(
        f"/trades/{trade_id}/cancel", json={"comment": "not agreed"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"

    history = await client.get(f"/trades/{trade_id}/history")
    body = history.json()
    states = [entry["state"] for entry in body["history"]]
    assert states == ["PENDING_CONFIRMATION", "CANCELLED"]
    assert body["history"][-1]["notes"] == "not agreed"


async def test_cancel_booked_trade(client):
    created = await _book_trade(client)
    assert created.status_code == 201
    await _confirm_trade(uuid.UUID(created.json()["trade_id"]))

    response = await client.post(f"/trades/{created.json()['trade_id']}/cancel", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


async def test_cancel_twice_is_conflict(client):
    created = await _book_trade(client)
    trade_id = created.json()["trade_id"]

    first = await client.post(f"/trades/{trade_id}/cancel", json={})
    assert first.status_code == 200

    second = await client.post(f"/trades/{trade_id}/cancel", json={})
    assert second.status_code == 409


async def test_cancel_404_for_unknown_trade(client):
    response = await client.post(
        "/trades/00000000-0000-0000-0000-000000000000/cancel", json={}
    )
    assert response.status_code == 404


async def test_amend_booked_trade(client):
    created = await _book_trade(client)
    assert created.status_code == 201
    trade_id = uuid.UUID(created.json()["trade_id"])
    await _confirm_trade(trade_id)

    response = await client.post(
        f"/trades/{trade_id}/amend",
        json={"notional_1": 2000000, "comment": "increased size"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "BOOKED"  # status stays BOOKED after an amend
    assert body["notional_1"] == 2000000
    assert body["notional_2"] == 2170000.0  # recomputed as notional_1 x rate
    assert body["comment"] == "increased size"

    history = await client.get(f"/trades/{trade_id}/history")
    states = [entry["state"] for entry in history.json()["history"]]
    assert states == ["PENDING_CONFIRMATION", "BOOKED", "AMENDED"]


async def test_amend_pending_trade_is_conflict(client):
    created = await _book_trade(client)
    trade_id = created.json()["trade_id"]

    response = await client.post(
        f"/trades/{trade_id}/amend", json={"comment": "too early"}
    )
    assert response.status_code == 409


async def test_amend_empty_payload_fails(client):
    created = await _book_trade(client)
    trade_id = created.json()["trade_id"]

    response = await client.post(f"/trades/{trade_id}/amend", json={})
    assert response.status_code == 422


async def test_amend_404_for_unknown_trade(client):
    response = await client.post(
        "/trades/00000000-0000-0000-0000-000000000000/amend", json={"comment": "x"}
    )
    assert response.status_code == 404


async def test_amend_currency_pair_derives_currencies(client):
    created = await _book_trade(client)
    assert created.status_code == 201
    trade_id = uuid.UUID(created.json()["trade_id"])
    await _confirm_trade(trade_id)

    response = await client.post(
        f"/trades/{trade_id}/amend",
        json={"currency_pair": "GBPUSD"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["currency_pair"] == "GBPUSD"
    assert body["currency_1"] == "GBP"
    assert body["currency_2"] == "USD"


async def test_amend_direction_and_counterparty(client):
    created = await _book_trade(client)
    assert created.status_code == 201
    trade_id = uuid.UUID(created.json()["trade_id"])
    await _confirm_trade(trade_id)

    response = await client.post(
        f"/trades/{trade_id}/amend",
        json={"direction": "SELL", "counterparty": "BANK_C"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["direction"] == "SELL"
    assert body["counterparty"] == "BANK_C"


async def test_amend_rate_and_settlement_updates_details(client):
    created = await _book_trade(client)
    assert created.status_code == 201
    trade_id = uuid.UUID(created.json()["trade_id"])
    trade_date = date.fromisoformat(created.json()["trade_date"])
    await _confirm_trade(trade_id)

    settlement = add_business_days(trade_date, 2).isoformat()
    response = await client.post(
        f"/trades/{trade_id}/amend",
        json={
            "instrument_details": {
                "instrument_type": "SPOT",
                "rate": 1.12,
                "settlement_date": settlement,
            }
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["instrument_details"]["rate"] == 1.12
    assert body["instrument_details"]["settlement_date"] == settlement
    assert body["notional_2"] == 1120000.0  # recomputed from the new rate


async def test_amend_rejects_out_of_window_spot_settlement(client):
    created = await _book_trade(client)
    assert created.status_code == 201
    trade_id = uuid.UUID(created.json()["trade_id"])
    trade_date = date.fromisoformat(created.json()["trade_date"])
    await _confirm_trade(trade_id)

    # SPOT settling 3 business days out is beyond the 2-day spot window
    beyond_spot = add_business_days(trade_date, 3).isoformat()
    response = await client.post(
        f"/trades/{trade_id}/amend",
        json={
            "instrument_details": {
                "instrument_type": "SPOT",
                "rate": 1.085,
                "settlement_date": beyond_spot,
            }
        },
    )
    assert response.status_code == 422


async def test_amend_rejects_instrument_type_mismatch(client):
    forward_payload = {
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
    created = await client.post("/trades", json=forward_payload)
    assert created.status_code == 201
    trade_id = uuid.UUID(created.json()["trade_id"])
    client.created_trade_ids.append(str(trade_id))
    await _confirm_trade(trade_id)

    # instrument_type is structural: a FORWARD trade cannot be amended with SPOT details
    response = await client.post(
        f"/trades/{trade_id}/amend",
        json={
            "instrument_details": {
                "instrument_type": "SPOT",
                "rate": 1.085,
                "settlement_date": spot_value_date(date.today()).isoformat(),
            }
        },
    )
    assert response.status_code == 422



async def test_confirm_pending_trade(client):
    created = await _book_trade(client)
    assert created.status_code == 201
    trade_id = created.json()["trade_id"]

    response = await client.post(
        f"/trades/{trade_id}/confirm", json={"comment": "confirmed"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "BOOKED"

    history = await client.get(f"/trades/{trade_id}/history")
    states = [e["state"] for e in history.json()["history"]]
    assert states == ["PENDING_CONFIRMATION", "BOOKED"]
    assert history.json()["history"][-1]["notes"] == "confirmed"


async def test_confirm_booked_trade_conflict(client):
    created = await _book_trade(client)
    trade_id = created.json()["trade_id"]
    first = await client.post(f"/trades/{trade_id}/confirm", json={})
    assert first.status_code == 200
    second = await client.post(f"/trades/{trade_id}/confirm", json={})
    assert second.status_code == 409
