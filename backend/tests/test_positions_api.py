import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.enums import TradeState, TradeStatus
from app.models.trade import Trade
from app.models.trade_state import TradeStateLog
from app.services import trade_lifecycle
from app.services.business_calendar import spot_value_date


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


BUY_EURUSD = {
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

SELL_EURUSD = {
    **BUY_EURUSD,
    "direction": "SELL",
    "notional_1": 400000,
    "counterparty": "BANK_B",
}


async def _book_trade(client, payload=BUY_EURUSD):
    response = await client.post("/trades", json=payload)
    if response.status_code == 201:
        client.created_trade_ids.append(response.json()["trade_id"])
    return response


async def _confirm_trade(trade_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        trade = await session.get(Trade, trade_id)
        trade.status = TradeStatus.BOOKED
        await trade_lifecycle.append_state(
            session, trade_id, TradeState.BOOKED, changed_by="operator"
        )
        await session.commit()


async def test_positions_aggregate_booked_trades(client):
    buy = await _book_trade(client, BUY_EURUSD)
    sell = await _book_trade(client, SELL_EURUSD)
    assert buy.status_code == sell.status_code == 201
    await _confirm_trade(uuid.UUID(buy.json()["trade_id"]))
    await _confirm_trade(uuid.UUID(sell.json()["trade_id"]))

    with patch(
        "app.api.routers.positions.get_rate",
        new=AsyncMock(return_value=(1.15, "2026-08-16")),
    ):
        response = await client.get("/positions")

    assert response.status_code == 200
    positions = response.json()
    assert len(positions) == 1
    eurusd = positions[0]
    assert eurusd["currency_pair"] == "EURUSD"
    assert eurusd["currency_1"] == "EUR"
    assert eurusd["currency_2"] == "USD"
    assert eurusd["count"] == 2
    assert eurusd["total_notional_1"] == 1400000.0
    assert eurusd["net_notional_1"] == 600000.0  # 1,000,000 buy - 400,000 sell
    # currency_2 legs derived at the live rate (1.15)
    assert eurusd["total_notional_2"] == 1610000.0  # 1,150,000 + 460,000
    assert eurusd["net_notional_2"] == 690000.0  # 1,150,000 - 460,000
    assert eurusd["mtm_value"] == 690000.0  # 600,000 * 1.15


async def test_positions_exclude_unconfirmed_and_cancelled(client):
    await _book_trade(client)  # stays PENDING_CONFIRMATION
    cancelled = await _book_trade(client)
    await client.post(f"/trades/{cancelled.json()['trade_id']}/cancel", json={})

    with patch(
        "app.api.routers.positions.get_rate",
        new=AsyncMock(return_value=(1.15, "2026-08-16")),
    ):
        response = await client.get("/positions")

    assert response.status_code == 200
    assert response.json() == []


async def test_positions_use_explicit_notional_2(client):
    payload = {
        **BUY_EURUSD,
        "notional_2": 1085000,  # booked at 1.085, even though the live rate is 1.15
    }
    created = await _book_trade(client, payload)
    assert created.status_code == 201
    await _confirm_trade(uuid.UUID(created.json()["trade_id"]))

    with patch(
        "app.api.routers.positions.get_rate",
        new=AsyncMock(return_value=(1.15, "2026-08-16")),
    ):
        response = await client.get("/positions")

    assert response.status_code == 200
    position = response.json()[0]
    assert position["total_notional_2"] == 1085000.0  # explicit, not derived
    assert position["net_notional_2"] == 1085000.0
    assert position["mtm_value"] == 1150000.0  # net_notional_1 * live rate


async def test_positions_notional_2_null_when_rate_unavailable(client):
    created = await _book_trade(client, BUY_EURUSD)  # no explicit notional_2
    assert created.status_code == 201
    await _confirm_trade(uuid.UUID(created.json()["trade_id"]))

    with patch(
        "app.api.routers.positions.get_rate",
        new=AsyncMock(side_effect=RuntimeError("upstream down")),
    ):
        response = await client.get("/positions")

    assert response.status_code == 200
    position = response.json()[0]
    assert position["total_notional_2"] is None
    assert position["net_notional_2"] is None
    assert position["mtm_value"] is None
