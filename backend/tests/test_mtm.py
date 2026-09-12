"""Pure unit tests for per-trade MTM helpers (no database required)."""

from datetime import date, timedelta

import pytest

from app.models.enums import (
    Currency,
    CurrencyPair,
    Direction,
    InstrumentType,
    TradeStatus,
)
from app.models.trade import Trade
from app.schemas.instrument_details import OptionDetails
from app.services.mtm import (
    compute_trade_mtm_usd,
    compute_trade_valuation_usd,
    premium_to_usd,
    to_usd,
)
from app.services.pricing.option_pricer import price_option_details

NOTIONAL = 1000000


def _trade(**overrides):
    """A BOOKED EURUSD BUY SPOT 1,000,000 @ 1.085 by default."""
    base = dict(
        instrument_type=InstrumentType.SPOT,
        currency_pair=CurrencyPair.EURUSD,
        direction=Direction.BUY,
        currency_1=Currency.EUR,
        notional_1=NOTIONAL,
        currency_2=Currency.USD,
        notional_2=1085000,
        trade_date=date(2026, 8, 14),
        counterparty="BANK_A",
        status=TradeStatus.BOOKED,
        comment=None,
        instrument_details={
            "instrument_type": "SPOT",
            "rate": 1.085,
            "settlement_date": "2026-08-19",
        },
    )
    base.update(overrides)
    return Trade(**base)


def _option_trade(pair=CurrencyPair.EURUSD, **overrides):
    """A BOOKED BUY CALL option with a premium paid in the quote currency."""
    expiry = date.today() + timedelta(days=120)
    premium_currency = "USD" if pair is CurrencyPair.EURUSD else "JPY"
    details = {
        "instrument_type": "OPTION",
        "option_type": "CALL",
        "strike_rate": 150.0 if pair is CurrencyPair.USDJPY else 1.15,
        "premium_date": date.today().isoformat(),
        "expiry_date": expiry.isoformat(),
        "delivery_date": (expiry + timedelta(days=2)).isoformat(),
        "premium": 3000000.0 if pair is CurrencyPair.USDJPY else 25000.0,
        "premium_currency": premium_currency,
        "exercise_style": "EUROPEAN",
    }
    defaults = {
        "instrument_type": InstrumentType.OPTION,
        "currency_pair": pair,
        "direction": Direction.BUY,
        "currency_1": Currency.USD if pair is CurrencyPair.USDJPY else Currency.EUR,
        "notional_1": NOTIONAL,
        "currency_2": Currency.JPY if pair is CurrencyPair.USDJPY else Currency.USD,
        "notional_2": None,
        "instrument_details": details,
    }
    defaults.update(overrides)
    return _trade(**defaults)


def test_to_usd_passes_usd_through_and_converts_jpy():
    assert to_usd(1000.0, "USD", 1.15) == 1000.0
    assert to_usd(150000.0, "JPY", 150.0) == pytest.approx(1000.0)


def test_premium_to_usd_handles_usd_and_quote_currency_premiums():
    assert premium_to_usd(25000.0, "USD", "USD", 1.15) == 25000.0
    assert premium_to_usd(3000000.0, "JPY", "JPY", 150.0) == pytest.approx(20000.0)
    with pytest.raises(ValueError):
        premium_to_usd(25000.0, "EUR", "USD", 1.15)


def test_eurusd_spot_buy_mtm():
    # 1,000,000 * (1.15 - 1.085) = 65,000 USD
    assert compute_trade_mtm_usd(_trade(), 1.15) == pytest.approx(65000.0)


def test_eurusd_spot_sell_mtm_is_negative():
    # -400,000 * (1.15 - 1.085) = -26,000 USD
    trade = _trade(direction=Direction.SELL, notional_1=400000, notional_2=434000)
    assert compute_trade_mtm_usd(trade, 1.15) == pytest.approx(-26000.0)


def test_forward_uses_booked_forward_rate():
    trade = _trade(
        instrument_type=InstrumentType.FORWARD,
        instrument_details={
            "instrument_type": "FORWARD",
            "rate": 1.09,
            "settlement_date": "2026-10-19",
        },
    )
    assert compute_trade_mtm_usd(trade, 1.15) == pytest.approx(60000.0)


def test_spot_mtm_is_none_when_live_rate_missing():
    assert compute_trade_mtm_usd(_trade(), None) is None


def test_usdjpy_spot_mtm_converts_jpy_pnl_to_usd():
    # BUY USD 1,000,000 vs JPY booked at 150, live 152 -> 2,000,000 JPY / 152
    trade = _trade(
        currency_pair=CurrencyPair.USDJPY,
        currency_1=Currency.USD,
        currency_2=Currency.JPY,
        notional_2=150000000,
        instrument_details={
            "instrument_type": "SPOT",
            "rate": 150.0,
            "settlement_date": "2026-08-19",
        },
    )
    assert compute_trade_mtm_usd(trade, 152.0) == pytest.approx(2000000.0 / 152.0)


def test_eurusd_option_mtm_reprices_against_paid_premium():
    trade = _option_trade()
    option = OptionDetails(**trade.instrument_details)
    priced = price_option_details(option, spot=1.15, vol=0.10, valuation_date=date.today())
    expected = NOTIONAL * priced.premium - 25000.0
    assert compute_trade_mtm_usd(trade, 1.15) == pytest.approx(expected)


def test_usdjpy_option_mtm_converts_jpy_premium_to_usd():
    trade = _option_trade(CurrencyPair.USDJPY)
    option = OptionDetails(**trade.instrument_details)
    priced = price_option_details(option, spot=150.0, vol=0.10, valuation_date=date.today())
    expected = (NOTIONAL * priced.premium - 3000000.0) / 150.0
    assert compute_trade_mtm_usd(trade, 150.0) == pytest.approx(expected)


def test_expired_option_mtm_is_none():
    trade = _option_trade(
        instrument_details={
            **_option_trade().instrument_details,
            "expiry_date": (date.today() - timedelta(days=1)).isoformat(),
        }
    )
    assert compute_trade_mtm_usd(trade, 1.15) is None


def test_spot_buy_valuation_greeks():
    # spot BUY 1,000,000 @ 1.085, live 1.15: delta = +notional, no option greeks
    valuation = compute_trade_valuation_usd(_trade(), 1.15)
    assert valuation is not None
    assert valuation.mtm_value == pytest.approx(65000.0)
    assert valuation.delta == pytest.approx(NOTIONAL)
    assert valuation.gamma == 0.0
    assert valuation.vega == 0.0
    assert valuation.theta == 0.0


def test_spot_sell_valuation_delta_is_negative():
    trade = _trade(direction=Direction.SELL, notional_1=400000, notional_2=434000)
    valuation = compute_trade_valuation_usd(trade, 1.15)
    assert valuation is not None
    assert valuation.mtm_value == pytest.approx(-26000.0)
    assert valuation.delta == pytest.approx(-400000.0)


def test_forward_valuation_delta_matches_spot():
    trade = _trade(
        instrument_type=InstrumentType.FORWARD,
        instrument_details={
            "instrument_type": "FORWARD",
            "rate": 1.09,
            "settlement_date": "2026-10-19",
        },
    )
    valuation = compute_trade_valuation_usd(trade, 1.15)
    assert valuation is not None
    assert valuation.mtm_value == pytest.approx(60000.0)
    assert valuation.delta == pytest.approx(NOTIONAL)
    assert valuation.gamma == 0.0
    assert valuation.vega == 0.0
    assert valuation.theta == 0.0


def test_valuation_is_none_when_live_rate_missing():
    assert compute_trade_valuation_usd(_trade(), None) is None


def test_option_valuation_greeks_scale_model_outputs():
    # delta is notional-scaled directly; gamma/vega per 1% -> /100, theta /365
    trade = _option_trade()
    option = OptionDetails(**trade.instrument_details)
    priced = price_option_details(option, spot=1.15, vol=0.10, valuation_date=date.today())
    valuation = compute_trade_valuation_usd(trade, 1.15)
    assert valuation is not None
    assert valuation.delta == pytest.approx(NOTIONAL * priced.greeks.delta)
    assert valuation.gamma == pytest.approx(NOTIONAL * priced.greeks.gamma / 100.0)
    assert valuation.vega == pytest.approx(NOTIONAL * priced.greeks.vega / 100.0)
    assert valuation.theta == pytest.approx(NOTIONAL * priced.greeks.theta / 365.0)
    assert valuation.mtm_value == pytest.approx(NOTIONAL * priced.premium - 25000.0)


def test_valuation_mtm_matches_mtm_helper():
    valuation = compute_trade_valuation_usd(_option_trade(), 1.15)
    assert valuation is not None
    assert valuation.mtm_value == compute_trade_mtm_usd(_option_trade(), 1.15)
