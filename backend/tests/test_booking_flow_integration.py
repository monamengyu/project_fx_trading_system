"""Integration tests for the trade booking flow.

These walk a trade through the whole lifecycle over the real API + database:
book -> confirm -> position -> amend -> cancel, verifying the append-only
lifecycle log, the blotter list, and the positions aggregation at each step.
They complement the per-endpoint tests in the other modules.
"""

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.trade import Trade
from app.models.trade_state import TradeStateLog
from app.services.business_calendar import (
    add_business_days,
    effective_trade_date,
    spot_value_date,
)


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


def _spot_payload(pair="EURUSD", direction="BUY", notional=1_000_000, rate=1.085):
    return {
        "instrument_type": "SPOT",
        "currency_pair": pair,
        "direction": direction,
        "currency_1": pair[:3],
        "notional_1": notional,
        "currency_2": pair[3:],
        "counterparty": "BANK_A",
        "instrument_details": {
            "instrument_type": "SPOT",
            "rate": rate,
            "settlement_date": spot_value_date(date.today()).isoformat(),
        },
    }


def _forward_payload():
    return {
        "instrument_type": "FORWARD",
        "currency_pair": "EURUSD",
        "direction": "BUY",
        "currency_1": "EUR",
        "notional_1": 1_000_000,
        "currency_2": "USD",
        "counterparty": "BANK_A",
        "instrument_details": {
            "instrument_type": "FORWARD",
            "rate": 1.092,
            "settlement_date": add_business_days(date.today(), 20).isoformat(),
        },
    }


def _payload_with_settlement(instrument_type, settlement):
    base = _forward_payload() if instrument_type == "FORWARD" else _spot_payload()
    return {
        **base,
        "instrument_details": {
            **base["instrument_details"],
            "instrument_type": instrument_type,
            "settlement_date": settlement.isoformat(),
        },
    }


async def _book_trade(client, payload):
    response = await client.post("/trades", json=payload)
    assert response.status_code == 201, response.text
    trade = response.json()
    client.created_trade_ids.append(trade["trade_id"])
    return trade


async def _history(client, trade_id):
    response = await client.get(f"/trades/{trade_id}/history")
    assert response.status_code == 200
    return response.json()["history"]


def _states(history):
    return [entry["state"] for entry in history]


async def _eurusd_position(client):
    with patch(
        "app.api.routers.positions.get_rate",
        new=AsyncMock(return_value=(1.085, "2026-08-19")),
    ):
        response = await client.get("/positions")
    assert response.status_code == 200
    for p in response.json():
        if p["currency_pair"] == "EURUSD":
            return p
    return None


# ---------------------------------------------------------------------------
# Full lifecycle flows
# ---------------------------------------------------------------------------


async def test_full_spot_booking_lifecycle(client):
    baseline = await _eurusd_position(client)  # may be None (no prior EURUSD pos)

    # 1. Book: PENDING_CONFIRMATION + initial lifecycle entry
    trade = await _book_trade(client, _spot_payload())
    trade_id = trade["trade_id"]
    assert trade["status"] == "PENDING_CONFIRMATION"
    assert trade["trade_date"] == effective_trade_date(date.today()).isoformat()
    assert _states(await _history(client, trade_id)) == ["PENDING_CONFIRMATION"]

    # 2. Blotter lists the new trade
    blotter = await client.get("/trades")
    assert trade_id in {t["trade_id"] for t in blotter.json()}

    # 3. Confirm: BOOKED, log appended, position count +1
    confirmed = await client.post(f"/trades/{trade_id}/confirm", json={"comment": "ok"})
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "BOOKED"
    assert _states(await _history(client, trade_id)) == [
        "PENDING_CONFIRMATION",
        "BOOKED",
    ]
    after_confirm = await _eurusd_position(client)
    assert after_confirm is not None
    assert after_confirm["count"] == (baseline["count"] if baseline else 0) + 1
    assert after_confirm["currency_1"] == "EUR"
    assert after_confirm["currency_2"] == "USD"

    # 4. Amend: stays BOOKED, notional updated, AMENDED logged
    amended = await client.post(
        f"/trades/{trade_id}/amend", json={"notional_1": 1_500_000}
    )
    assert amended.status_code == 200
    assert amended.json()["status"] == "BOOKED"
    assert amended.json()["notional_1"] == 1_500_000
    assert _states(await _history(client, trade_id)) == [
        "PENDING_CONFIRMATION",
        "BOOKED",
        "AMENDED",
    ]

    # 5. Cancel: CANCELLED, log appended, dropped from positions
    cancelled = await client.post(
        f"/trades/{trade_id}/cancel", json={"comment": "client changed mind"}
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert _states(await _history(client, trade_id)) == [
        "PENDING_CONFIRMATION",
        "BOOKED",
        "AMENDED",
        "CANCELLED",
    ]
    after_cancel = await _eurusd_position(client)
    assert (after_cancel["count"] if after_cancel else 0) == (
        baseline["count"] if baseline else 0
    )


async def test_forward_booking_lifecycle(client):
    baseline = await _eurusd_position(client)
    baseline_net = baseline["net_notional_1"] if baseline else 0.0

    trade = await _book_trade(client, _forward_payload())
    trade_id = trade["trade_id"]
    assert trade["status"] == "PENDING_CONFIRMATION"
    assert trade["instrument_type"] == "FORWARD"

    confirmed = await client.post(f"/trades/{trade_id}/confirm", json={})
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "BOOKED"

    position = await _eurusd_position(client)
    assert position["count"] == (baseline["count"] if baseline else 0) + 1
    # a BUY of 1,000,000 EUR increases the net EUR position by that amount
    assert position["net_notional_1"] == pytest.approx(baseline_net + 1_000_000)


# ---------------------------------------------------------------------------
# Rejected transitions
# ---------------------------------------------------------------------------


def _next_saturday(start):
    d = start
    while True:
        d += timedelta(days=1)
        if d.weekday() == 5:
            return d


async def test_booking_rejects_weekend_settlement(client):
    weekend = _next_saturday(spot_value_date(date.today()))
    response = await client.post(
        "/trades", json=_payload_with_settlement("FORWARD", weekend)
    )
    assert response.status_code == 422


async def test_booking_rejects_out_of_window_settlement(client):
    # SPOT beyond the spot value date must be booked as FORWARD
    beyond_spot = add_business_days(effective_trade_date(date.today()), 3)
    response = await client.post(
        "/trades",
        json=_payload_with_settlement("SPOT", beyond_spot),
    )
    assert response.status_code == 422
    # FORWARD settling at the spot value date is not a forward
    response = await client.post(
        "/trades",
        json=_payload_with_settlement("FORWARD", spot_value_date(date.today())),
    )
    assert response.status_code == 422


async def test_confirm_already_booked_trade_conflicts(client):
    trade = await _book_trade(client, _spot_payload())
    await client.post(f"/trades/{trade['trade_id']}/confirm", json={})
    response = await client.post(f"/trades/{trade['trade_id']}/confirm", json={})
    assert response.status_code == 409


async def test_cancel_already_cancelled_trade_conflicts(client):
    trade = await _book_trade(client, _spot_payload())
    await client.post(f"/trades/{trade['trade_id']}/cancel", json={})
    response = await client.post(f"/trades/{trade['trade_id']}/cancel", json={})
    assert response.status_code == 409


async def test_confirm_cancelled_trade_conflicts(client):
    trade = await _book_trade(client, _spot_payload())
    await client.post(f"/trades/{trade['trade_id']}/cancel", json={})
    response = await client.post(f"/trades/{trade['trade_id']}/confirm", json={})
    assert response.status_code == 409


async def test_amend_pending_or_cancelled_trade_conflicts(client):
    pending = await _book_trade(client, _spot_payload())
    response = await client.post(
        f"/trades/{pending['trade_id']}/amend", json={"comment": "nope"}
    )
    assert response.status_code == 409

    trade = await _book_trade(client, _spot_payload())
    await client.post(f"/trades/{trade['trade_id']}/cancel", json={})
    response = await client.post(
        f"/trades/{trade['trade_id']}/amend", json={"comment": "nope"}
    )
    assert response.status_code == 409


async def test_unknown_trade_transitions_404(client):
    tid = str(uuid.uuid4())
    assert (await client.post(f"/trades/{tid}/confirm", json={})).status_code == 404
    assert (await client.post(f"/trades/{tid}/cancel", json={})).status_code == 404
    assert (await client.post(f"/trades/{tid}/amend", json={"comment": "x"})).status_code == 404
