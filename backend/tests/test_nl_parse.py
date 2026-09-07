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


def test_registry_lists_openrouter_models_when_keyed(monkeypatch):
    from app.core.config import settings
    from app.services.nl_parse.models import available_models

    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-test")
    ids = [m.id for m in available_models()]
    assert any(i.startswith("openai/") for i in ids)
    assert any("claude-sonnet-4-5" in i for i in ids)
    assert any(i.startswith("google/") for i in ids)


def test_registry_hides_openrouter_models_without_key(monkeypatch):
    from app.core.config import settings
    from app.services.nl_parse.models import available_models

    monkeypatch.setattr(settings, "openrouter_api_key", None)
    ids = [m.id for m in available_models()]
    assert not any(m.kind == "openrouter" for m in available_models())
    assert "rule-based" in ids
    assert "llama3.2:3b" in ids
    assert "qwen2.5:3b" in ids


def test_registry_lists_all_ollama_models(monkeypatch):
    from app.core.config import settings
    from app.services.nl_parse.models import available_models

    monkeypatch.setattr(settings, "openrouter_api_key", None)
    ollama_ids = [m.id for m in available_models() if m.kind == "ollama"]
    assert set(ollama_ids) == {
        "llama3.2:3b",
        "qwen2.5:3b",
        "gemma2:2b",
        "phi3.5",
    }


def test_baseline_parses_spot():
    result = parse_rule_based("Buy 1 million euros against dollars, spot at 1.085")
    assert result["instrument_type"] == "SPOT"
    assert result["currency_pair"] == "EURUSD"
    assert result["direction"] == "BUY"
    assert result["notional_1"] == 1_000_000
    assert result["instrument"]["rate"] == 1.085


@pytest.mark.parametrize(
    "text, pair, direction, notional",
    [
        # USDJPY
        ("Sell 5 million yen for usd spot at 152.5", "USDJPY", "SELL", 5_000_000),
        ("Buy 3 million usd/jpy spot at 152.5", "USDJPY", "BUY", 3_000_000),
        # USDCHF / USDCAD
        ("Buy 4 million swiss francs for usd spot at 0.89", "USDCHF", "BUY", 4_000_000),
        ("Sell 4 million usd against canadian dollars spot at 1.36", "USDCAD", "SELL", 4_000_000),
        # AUDUSD / NZDUSD
        ("Buy 5 million aussie dollars for usd spot at 0.66", "AUDUSD", "BUY", 5_000_000),
        ("Sell 8 million kiwi for usd spot at 0.61", "NZDUSD", "SELL", 8_000_000),
        ("Buy 5 million usd against new zealand dollars spot at 0.61", "NZDUSD", "BUY", 5_000_000),
        # USDCNH / USDHKD
        ("Buy 5 million usd against yuan spot at 7.2", "USDCNH", "BUY", 5_000_000),
        ("Sell 2 million usd against hong kong dollars spot at 7.8", "USDHKD", "SELL", 2_000_000),
        # USDSGD / USDSEK / USDNOK
        ("Sell usdsgd 1 m spot at 1.35", "USDSGD", "SELL", 1_000_000),
        ("Buy 3 million singapore dollars for usd spot at 1.30", "USDSGD", "BUY", 3_000_000),
        ("Sell 5 million usd against swedish krona spot at 10.5", "USDSEK", "SELL", 5_000_000),
        ("Buy 5 million norwegian kroner for usd spot at 10.2", "USDNOK", "BUY", 5_000_000),
        # USDMXN / USDZAR / USDTRY
        ("Sell 6 million usd against mexican pesos spot at 18.9", "USDMXN", "SELL", 6_000_000),
        ("Buy 10 million usd against south african rand spot at 18.5", "USDZAR", "BUY", 10_000_000),
        ("Sell 3 million usd against turkish lira spot at 34.2", "USDTRY", "SELL", 3_000_000),
    ],
)
def test_baseline_parses_expanded_pairs(text, pair, direction, notional):
    result = parse_rule_based(text)
    assert result["instrument_type"] == "SPOT"
    assert result["currency_pair"] == pair
    assert result["direction"] == direction
    assert result["notional_1"] == notional


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


_VALID_SPOT_CONTENT = {
    "instrument_type": "SPOT",
    "currency_pair": "EURUSD",
    "direction": "BUY",
    "notional_1": 1_000_000,
    "counterparty": "BANK_A",
    "comment": None,
    "instrument": {"instrument_type": "SPOT", "rate": 1.085},
}


async def test_parse_trade_propagates_usage_from_model():
    from app.services.nl_parse.clients import Completion
    from app.services.nl_parse.parser import parse_trade

    class FakeClient:
        async def complete_json(self, system, user):
            return Completion(
                content=_VALID_SPOT_CONTENT,
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )

    with patch("app.services.nl_parse.parser.get_client", return_value=FakeClient()):
        result = await parse_trade("Buy EURUSD spot", model_id="llama3.2:3b")
    assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


async def test_parse_trade_accumulates_usage_across_retry():
    from app.services.nl_parse.clients import Completion
    from app.services.nl_parse.parser import parse_trade

    calls = {"n": 0}

    class FakeClient:
        async def complete_json(self, system, user):
            calls["n"] += 1
            if calls["n"] == 1:
                # Invalid content triggers the retry; it still consumed tokens.
                return Completion(content={"bogus": True}, usage={"total_tokens": 15})
            return Completion(content=_VALID_SPOT_CONTENT, usage={"total_tokens": 12})

    with patch("app.services.nl_parse.parser.get_client", return_value=FakeClient()):
        result = await parse_trade("Buy EURUSD spot", model_id="llama3.2:3b")
    assert calls["n"] == 2
    assert result.usage == {"total_tokens": 27}
    assert result.model == "llama3.2:3b"
