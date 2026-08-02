import pytest
from pydantic import ValidationError

from app.schemas.trade import TradeCreate


def test_spot_trade_valid():
    trade = TradeCreate(
        instrument_type="SPOT",
        currency_pair="EURUSD",
        direction="BUY",
        currency_1="EUR",
        notional_1=1000000,
        currency_2="USD",
        counterparty="BANK_A",
        instrument_details={"rate": 1.085, "settlement_date": "2026-08-01"},
    )
    assert trade.instrument_details["rate"] == 1.085


def test_option_trade_valid():
    trade = TradeCreate(
        instrument_type="OPTION",
        currency_pair="EURUSD",
        direction="BUY",
        currency_1="EUR",
        notional_1=1000000,
        currency_2="USD",
        counterparty="BANK_A",
        instrument_details={"option_type": "CALL", "strike_rate": 1.085, "premium_date": "2026-07-30", "expiry_date": "2026-09-15", "delivery_date": "2026-09-17", "premium": 12500, "premium_currency": "USD", "exercise_style": "EUROPEAN"},
    )
    assert trade.instrument_details["strike_rate"] == 1.085


def test_option_trade_missing_strike_rate_fails():
    with pytest.raises(ValidationError):
        TradeCreate(
            instrument_type="OPTION",
            currency_pair="EURUSD",
            direction="BUY",
            currency_1="EUR",
            notional_1=1000000,
            currency_2="USD",
            counterparty="BANK_A",
            instrument_details={"option_type": "CALL"},  # missing required fields
        )