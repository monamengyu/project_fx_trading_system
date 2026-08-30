"""Unit tests for the NL trade parsing service (baseline parser + resolver)."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.models.enums import InstrumentType
from app.services.business_calendar import effective_trade_date, spot_value_date
from app.services.nl_parse.baseline import ParseError, parse_rule_based
from app.services.nl_parse.parser import draft_to_trade_create
from app.services.nl_parse.schemas import NLTradeDraft, ParsedInstrument


def _draft(**overrides):
    base = {
        "instrument_type": "SPOT",
        "currency_pair": "EURUSD",
        "direction": "BUY",
        "notional_1": 1_000_000,
        "counterparty": "BANK_A",
        "comment": None,
        "instrument": ParsedInstrument(instrument_type="SPOT", rate=1.085),
    }
    base.update(overrides)
    return NLTradeDraft(**base)


def test_registry_lists_anthropic_models_when_keyed(monkeypatch):
    from app.core.config import settings
    from app.services.nl_parse.models import available_models

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test")
    ids = [m.id for m in available_models()]
    assert any(i.startswith("anthropic-") for i in ids)
    assert any("claude-sonnet-4-5" in i for i in ids)
    assert any("claude-opus-5" in i for i in ids)


def test_baseline_parses_spot():
    result = parse_rule_based("Buy 1 million euros against dollars, spot at 1.085")
    assert result["instrument_type"] == "SPOT"
    assert result["currency_pair"] == "EURUSD"
    assert result["direction"] == "BUY"
    assert result["notional_1"] == 1_000_000
    assert result["instrument"]["rate"] == 1.085


def test_baseline_parses_forward_with_explicit_date():
    result = parse_rule_based("Sell 500k GBP for USD settling 2026-11-30 at 1.27")
    assert result["instrument_type"] == "FORWARD"
    assert result["currency_pair"] == "GBPUSD"
    assert result["direction"] == "SELL"
    assert result["notional_1"] == 500_000
    assert result["instrument"]["settlement_date"] == "2026-11-30"


def test_baseline_parses_call_option():
    result = parse_rule_based(
        "Buy a European call on EURUSD strike 1.10 expiring 2026-12-18, "
        "notional 500k, premium 25000 USD"
    )
    assert result["instrument_type"] == "OPTION"
    inst = result["instrument"]
    assert inst["option_type"] == "CALL"
    assert inst["strike_rate"] == 1.10
    assert inst["expiry_date"] == "2026-12-18"
    assert inst["premium"] == 25_000
    assert inst["premium_currency"] == "USD"
    assert inst["exercise_style"] == "EUROPEAN"


def test_baseline_rejects_unparseable():
    with pytest.raises(ParseError):
        parse_rule_based("please do something vague")
    with pytest.raises(ParseError):
        parse_rule_based("Buy some things against dollars, spot")


async def test_resolver_validates_spot_trade():
    draft = _draft()
    trade = await draft_to_trade_create(draft)
    assert trade.instrument_type == InstrumentType.SPOT
    assert trade.currency_1 == "EUR"
    assert trade.currency_2 == "USD"
    assert trade.instrument_details.rate == 1.085


async def test_resolver_fills_market_rate_when_missing():
    draft = _draft()
    draft.instrument.rate = None
    with patch(
        "app.services.nl_parse.parser.get_rate",
        new=AsyncMock(return_value=(1.15, date(2026, 8, 19))),
    ):
        trade = await draft_to_trade_create(draft)
    assert trade.instrument_details.rate == 1.15


async def test_resolver_defaults_missing_option_fields():
    draft = _draft(
        instrument_type="OPTION",
        instrument=ParsedInstrument(
            instrument_type="OPTION",
            option_type="PUT",
            strike_rate=1.10,
            expiry_date=date(2026, 12, 18),
        ),
    )
    trade = await draft_to_trade_create(draft)
    details = trade.instrument_details
    assert details.delivery_date == date(2026, 12, 18)  # defaults to expiry
    assert details.premium == 0.0
    assert details.premium_currency == "USD"
    assert details.exercise_style == "EUROPEAN"
    assert details.premium_date == spot_value_date(effective_trade_date(date.today()))


async def test_resolver_rejects_bad_settlement_window():
    draft = _draft(
        instrument_type="FORWARD",
        instrument=ParsedInstrument(
            instrument_type="FORWARD",
            rate=1.09,
            settlement_date=spot_value_date(date.today()),  # not beyond spot
        ),
    )
    with pytest.raises(ParseError):
        await draft_to_trade_create(draft)
