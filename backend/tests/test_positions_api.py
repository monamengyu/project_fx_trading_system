import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.enums import TradeState, TradeStatus
from app.models.trade import Trade
from app.models.trade_state import TradeStateLog
from app.schemas.instrument_details import OptionDetails
from app.services import trade_lifecycle
from app.services.business_calendar import spot_value_date
from app.services.pricing.option_pricer import price_option_details


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

LIVE_RATE = 1.15


def _option_payload():
    """A BUY EURUSD CALL 1,000,000 @1.15 struck, premium paid in USD."""
    expiry = date.today() + timedelta(days=120)
    return {
        "instrument_type": "OPTION",
        "currency_pair": "EURUSD",
        "direction": "BUY",
        "currency_1": "EUR",
        "notional_1": 1000000,
        "currency_2": "USD",
        "counterparty": "BANK_A",
        "instrument_details": {
            "instrument_type": "OPTION",
            "option_type": "CALL",
            "strike_rate": 1.15,
            "premium_date": date.today().isoformat(),
            "expiry_date": expiry.isoformat(),
            "delivery_date": (expiry + timedelta(days=2)).isoformat(),
            "premium": 25000.0,
            "premium_currency": "USD",
            "exercise_style": "EUROPEAN",
        },
    }


def _usdjpy_option_payload():
    """A BUY USDJPY CALL 1,000,000 @150 struck with premium paid in JPY."""
    expiry = date.today() + timedelta(days=120)
    return {
        "instrument_type": "OPTION",
        "currency_pair": "USDJPY",
        "direction": "BUY",
        "currency_1": "USD",
        "notional_1": 1000000,
        "currency_2": "JPY",
        "counterparty": "BANK_A",
        "instrument_details": {
            "instrument_type": "OPTION",
            "option_type": "CALL",
            "strike_rate": 150.0,
            "premium_date": date.today().isoformat(),
            "expiry_date": expiry.isoformat(),
            "delivery_date": (expiry + timedelta(days=2)).isoformat(),
            "premium": 3000000.0,
            "premium_currency": "JPY",
            "exercise_style": "EUROPEAN",
        },
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


async def _positions(client):
    response = await client.get("/positions")
    assert response.status_code == 200
    return response.json()


def _find(positions, pair):
    for position in positions:
        if position["currency_pair"] == pair:
            return position
    return None


async def test_positions_aggregate_booked_trades(client):
    buy = await _book_trade(client, BUY_EURUSD)
    sell = await _book_trade(client, SELL_EURUSD)
    assert buy.status_code == sell.status_code == 201
    await _confirm_trade(uuid.UUID(buy.json()["trade_id"]))
    await _confirm_trade(uuid.UUID(sell.json()["trade_id"]))

    with patch(
        "app.api.routers.positions.get_rate",
        new=AsyncMock(return_value=(LIVE_RATE, "2026-08-16")),
    ):
        positions = await _positions(client)

    eurusd = _find(positions, "EURUSD")
    assert eurusd is not None
    assert eurusd["currency_1"] == "EUR"
    assert eurusd["currency_2"] == "USD"
    assert eurusd["total_notional_1"] == 1400000.0
    assert eurusd["net_notional_1"] == 600000.0  # 1,000,000 buy - 400,000 sell
    # currency_2 legs derived at the live rate (1.15)
    assert eurusd["total_notional_2"] == 1610000.0  # 1,150,000 + 460,000
    assert eurusd["net_notional_2"] == 690000.0  # 1,150,000 - 460,000
    # delta is the net currency_1 exposure; no options -> other greeks are 0
    assert eurusd["delta"] == 600000.0
    assert eurusd["gamma"] == 0.0
    assert eurusd["vega"] == 0.0
    assert eurusd["theta"] == 0.0
    # MTM = current (live 1.15) minus executed (1.085) in USD:
    #   1,000,000 * 0.065 - 400,000 * 0.065 = 39,000
    assert eurusd["mtm_value"] == 39000.0


async def test_positions_exclude_unconfirmed_and_cancelled(client):
    await _book_trade(client)  # stays PENDING_CONFIRMATION
    cancelled = await _book_trade(client)
    await client.post(f"/trades/{cancelled.json()['trade_id']}/cancel", json={})

    with patch(
        "app.api.routers.positions.get_rate",
        new=AsyncMock(return_value=(LIVE_RATE, "2026-08-16")),
    ):
        positions = await _positions(client)

    assert positions == []


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
        new=AsyncMock(return_value=(LIVE_RATE, "2026-08-16")),
    ):
        positions = await _positions(client)

    eurusd = _find(positions, "EURUSD")
    assert eurusd is not None
    assert eurusd["total_notional_2"] == 1085000.0  # explicit, not derived
    assert eurusd["net_notional_2"] == 1085000.0
    assert eurusd["delta"] == 1000000.0
    assert eurusd["mtm_value"] == 65000.0  # 1,000,000 * (1.15 - 1.085)


async def test_positions_notional_2_null_when_rate_unavailable(client):
    created = await _book_trade(client, BUY_EURUSD)  # no explicit notional_2
    assert created.status_code == 201
    await _confirm_trade(uuid.UUID(created.json()["trade_id"]))

    with patch(
        "app.api.routers.positions.get_rate",
        new=AsyncMock(side_effect=RuntimeError("upstream down")),
    ):
        positions = await _positions(client)

    eurusd = _find(positions, "EURUSD")
    assert eurusd is not None
    assert eurusd["total_notional_2"] is None
    assert eurusd["net_notional_2"] is None
    # delta does not depend on the live rate, so it is still reported
    assert eurusd["delta"] == 1000000.0
    assert eurusd["gamma"] == 0.0
    assert eurusd["vega"] == 0.0
    assert eurusd["theta"] == 0.0
    assert eurusd["mtm_value"] is None


async def test_positions_option_leg_repriced_with_greeks_and_usd_mtm(client):
    payload = _option_payload()
    created = await _book_trade(client, payload)
    assert created.status_code == 201
    await _confirm_trade(uuid.UUID(created.json()["trade_id"]))

    with patch(
        "app.api.routers.positions.get_rate",
        new=AsyncMock(return_value=(LIVE_RATE, "2026-08-16")),
    ):
        positions = await _positions(client)

    eurusd = _find(positions, "EURUSD")
    assert eurusd is not None
    # the option contributes its contract notional to the currency_1 side only
    assert eurusd["total_notional_1"] == 1000000.0
    assert eurusd["net_notional_1"] == 1000000.0
    assert eurusd["total_notional_2"] == 0.0
    assert eurusd["net_notional_2"] == 0.0

    # re-run the same repricing the router does, to derive expected greeks/MTM
    option = OptionDetails(**payload["instrument_details"])
    priced = price_option_details(
        option, spot=LIVE_RATE, vol=0.10, valuation_date=date.today()
    )
    notional = 1000000
    assert eurusd["delta"] == pytest.approx(round(notional * priced.greeks.delta, 2))
    assert eurusd["gamma"] == pytest.approx(round(notional * priced.greeks.gamma, 2))
    assert eurusd["vega"] == pytest.approx(round(notional * priced.greeks.vega, 2))
    assert eurusd["theta"] == pytest.approx(round(notional * priced.greeks.theta, 2))
    # premium paid (25,000 USD) was below the current premium -> positive P&L
    expected_mtm = round(notional * priced.premium - 25000.0, 2)
    assert eurusd["mtm_value"] == pytest.approx(expected_mtm)


async def test_positions_usdjpy_option_converts_jpy_premium_to_usd(client):
    payload = _usdjpy_option_payload()
    created = await _book_trade(client, payload)
    assert created.status_code == 201
    await _confirm_trade(uuid.UUID(created.json()["trade_id"]))

    jpy_rate = 150.0
    with patch(
        "app.api.routers.positions.get_rate",
        new=AsyncMock(return_value=(jpy_rate, "2026-08-16")),
    ):
        positions = await _positions(client)

    usdjpy = _find(positions, "USDJPY")
    assert usdjpy is not None
    assert usdjpy["total_notional_1"] == 1000000.0
    assert usdjpy["net_notional_1"] == 1000000.0
    assert usdjpy["total_notional_2"] == 0.0
    assert usdjpy["net_notional_2"] == 0.0

    option = OptionDetails(**payload["instrument_details"])
    priced = price_option_details(
        option, spot=jpy_rate, vol=0.10, valuation_date=date.today()
    )
    notional = 1000000
    assert usdjpy["delta"] == pytest.approx(round(notional * priced.greeks.delta, 2))
    # BS premium is per USD unit in JPY; convert both current and paid premium
    # to USD by dividing by the live JPY/USD rate.
    expected_mtm = round(
        (notional * priced.premium - 3000000.0) / jpy_rate, 2
    )
    assert usdjpy["mtm_value"] == pytest.approx(expected_mtm)
