"""Unit tests for the NL trade parsing service (baseline parser + resolver)."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.models.enums import CurrencyPair, InstrumentType
from app.services.business_calendar import (
    add_business_days,
    current_trade_date,
    effective_trade_date,
    override_trade_date,
    spot_value_date,
)
from app.services.market_data.pairs import SUPPORTED_PAIRS
from app.services.nl_parse.baseline import ParseError, parse_rule_based
from app.services.nl_parse.parser import (
    DEFAULT_FORWARD_TENOR_DAYS,
    draft_to_trade_create,
    parse_trade,
    resolve_draft,
)
from app.services.nl_parse.prompts import build_system_prompt
from app.services.nl_parse.schemas import NLTradeDraft, ParsedInstrument
from evaluation.frozen_rates import FrozenRateProvider, MissingFrozenRate


# A fixed Monday, and the spot value date that belongs to it. Pinning the trade
# date is what makes a recorded corpus replayable on a later day.
PINNED_DAY = date(2026, 6, 1)
PINNED_SPOT = date(2026, 6, 3)


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
    assert any(i.startswith("anthropic/") for i in ids)
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


async def test_pinned_date_keeps_resolver_and_validator_in_step():
    """Regression: pinning only the resolver made the validator reject its output.

    The settlement date below is valid for the pinned day but in the past
    relative to the real today, so this only passes while the resolver and
    ``TradeCreate``'s settlement-window validator read the same day.
    """
    before = current_trade_date()
    draft = _draft(
        instrument=ParsedInstrument(
            instrument_type="SPOT", rate=1.085, settlement_date=PINNED_SPOT
        )
    )
    with override_trade_date(PINNED_DAY):
        assert current_trade_date() == PINNED_DAY
        resolved = await resolve_draft(draft)
    assert current_trade_date() == before
    assert resolved.defaulted_fields == []
    assert resolved.trade.instrument_details.settlement_date == PINNED_SPOT


async def test_resolver_derives_spot_settlement_from_the_pin():
    draft = _draft()
    with override_trade_date(PINNED_DAY):
        resolved = await resolve_draft(draft)
    assert resolved.trade.instrument_details.settlement_date == PINNED_SPOT
    assert resolved.defaulted_fields == ["settlement_date"]


async def test_resolver_derives_forward_settlement_from_the_pin():
    draft = _draft(
        instrument_type="FORWARD",
        instrument=ParsedInstrument(instrument_type="FORWARD", rate=1.09),
    )
    with override_trade_date(PINNED_DAY):
        resolved = await resolve_draft(draft)
    assert resolved.trade.instrument_details.settlement_date == add_business_days(
        PINNED_DAY, DEFAULT_FORWARD_TENOR_DAYS
    )


async def test_resolver_records_not_one_default_for_a_complete_option_draft():
    draft = _draft(
        instrument_type="OPTION",
        instrument=ParsedInstrument(
            instrument_type="OPTION",
            option_type="PUT",
            strike_rate=1.10,
            premium_date=date(2026, 6, 3),
            expiry_date=date(2026, 12, 18),
            delivery_date=date(2026, 12, 18),
            premium=25_000.0,
            premium_currency="USD",
            exercise_style="EUROPEAN",
        ),
    )
    with override_trade_date(PINNED_DAY):
        resolved = await resolve_draft(draft)
    assert resolved.defaulted_fields == []


async def test_resolver_enumerates_every_invented_option_default():
    draft = _draft(
        instrument_type="OPTION",
        instrument=ParsedInstrument(
            instrument_type="OPTION", expiry_date=date(2026, 12, 18)
        ),
    )
    with override_trade_date(PINNED_DAY):
        resolved = await resolve_draft(draft)
    assert set(resolved.defaulted_fields) == {
        "option_type",
        "strike_rate",
        "premium_date",
        "delivery_date",
        "premium",
        "premium_currency",
        "exercise_style",
    }
    assert resolved.trade.instrument_details.premium_date == PINNED_SPOT


async def test_resolver_does_not_flag_a_market_resolved_rate():
    draft = _draft()
    draft.instrument.rate = None

    async def provider(pair):
        return 1.2345, date(2026, 6, 1)

    with override_trade_date(PINNED_DAY):
        resolved = await resolve_draft(draft, rate_provider=provider)
    assert resolved.trade.instrument_details.rate == 1.2345
    assert "rate" not in resolved.defaulted_fields


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

    class FakeClient:
        async def complete_json(self, messages):
            return Completion(
                content=_VALID_SPOT_CONTENT,
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )

    with patch("app.services.nl_parse.parser.get_client", return_value=FakeClient()):
        result = await parse_trade("Buy EURUSD spot", model_id="llama3.2:3b")
    assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


async def test_parse_trade_accumulates_usage_across_retry():
    from app.services.nl_parse.clients import Completion

    calls = {"n": 0}

    class FakeClient:
        async def complete_json(self, messages):
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


async def test_parse_trade_reports_defaults_from_the_resolver():
    from app.services.nl_parse.clients import Completion

    class FakeClient:
        async def complete_json(self, messages):
            return Completion(content=_VALID_SPOT_CONTENT, usage={})

    with override_trade_date(PINNED_DAY):
        with patch("app.services.nl_parse.parser.get_client", return_value=FakeClient()):
            result = await parse_trade("Buy EURUSD spot", model_id="llama3.2:3b")

    assert result.defaulted_fields == ["settlement_date"]
    assert result.trade.instrument_details.settlement_date == PINNED_SPOT


async def test_parse_trade_uses_the_injected_rate_provider():
    from app.services.nl_parse.clients import Completion

    content = dict(_VALID_SPOT_CONTENT)
    content["instrument"] = {"instrument_type": "SPOT", "rate": None}
    used = []

    class FakeClient:
        async def complete_json(self, messages):
            return Completion(content=content, usage={})

    async def provider(pair):
        used.append(pair)
        return 1.4321, date(2026, 6, 1)

    with override_trade_date(PINNED_DAY):
        with patch("app.services.nl_parse.parser.get_client", return_value=FakeClient()):
            result = await parse_trade(
                "Buy EURUSD spot", model_id="llama3.2:3b", rate_provider=provider
            )

    assert used == [CurrencyPair.EURUSD]
    assert result.trade.instrument_details.rate == 1.4321


async def test_parse_trade_sends_the_worked_examples():
    from app.services.nl_parse.clients import Completion
    from app.services.nl_parse.prompts import build_messages

    seen = []

    class FakeClient:
        async def complete_json(self, messages):
            seen.append(messages)
            return Completion(content=_VALID_SPOT_CONTENT, usage={})

    with patch("app.services.nl_parse.parser.get_client", return_value=FakeClient()):
        await parse_trade("Buy EURUSD spot", model_id="llama3.2:3b")

    assert seen == [build_messages("Buy EURUSD spot")]
    assert [m["role"] for m in seen[0]] == [
        "system",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert seen[0][-1] == {"role": "user", "content": "Buy EURUSD spot"}


async def test_retry_corrects_only_the_final_turn_and_keeps_the_examples():
    from app.services.nl_parse.clients import Completion

    seen = []

    class FakeClient:
        async def complete_json(self, messages):
            seen.append(messages)
            if len(seen) == 1:
                return Completion(content={"bogus": True}, usage={})
            return Completion(content=_VALID_SPOT_CONTENT, usage={})

    with patch("app.services.nl_parse.parser.get_client", return_value=FakeClient()):
        await parse_trade("Buy EURUSD spot", model_id="llama3.2:3b")

    assert len(seen) == 2
    assert seen[1][:-1] == seen[0][:-1]
    assert seen[1][-1]["content"].startswith("Buy EURUSD spot")
    assert "Your previous output was invalid" in seen[1][-1]["content"]


async def test_baseline_client_reads_the_final_user_turn():
    from app.services.nl_parse.clients import BaselineClient
    from app.services.nl_parse.prompts import build_messages

    messages = build_messages("Buy 5 million norwegian kroner for usd spot at 10.2")
    # The first user turn is a worked example, not the text to be parsed.
    assert messages[1]["content"] != messages[-1]["content"]

    with override_trade_date(PINNED_DAY):
        completion = await BaselineClient().complete_json(messages)

    assert completion.content["currency_pair"] == "USDNOK"
    assert completion.content["instrument"]["settlement_date"] == PINNED_SPOT.isoformat()


async def test_baseline_client_rejects_a_conversation_without_a_user_turn():
    from app.services.nl_parse.clients import BaselineClient

    with pytest.raises(ValueError):
        await BaselineClient().complete_json([{"role": "system", "content": "nothing to parse"}])


@pytest.mark.parametrize("kind", ["openai-compatible", "openrouter"])
async def test_chat_request_carries_the_whole_conversation(monkeypatch, kind):
    from app.services.nl_parse import clients as clients_module
    from app.services.nl_parse.prompts import build_messages

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [{"message": {"content": '{"instrument_type": "SPOT"}'}}],
                "usage": {"total_tokens": 3},
                "model": "served-model",
            }

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, json=None, headers=None):
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(clients_module.httpx, "AsyncClient", FakeAsyncClient)
    if kind == "openrouter":
        client = clients_module.OpenRouterClient("test-key", "openai/gpt-5.6-luna")
    else:
        client = clients_module.OpenAICompatClient(
            "http://localhost:11434/v1", None, "llama3.2:3b"
        )

    messages = build_messages("Buy EURUSD spot")
    completion = await client.complete_json(messages)

    assert captured["payload"]["messages"] == messages
    assert len(captured["payload"]["messages"]) == 8
    assert completion.content == {"instrument_type": "SPOT"}
    assert completion.model == "served-model"


def test_system_prompt_honours_the_pin():
    with override_trade_date(PINNED_DAY):
        prompt = build_system_prompt()
    assert PINNED_DAY.isoformat() in prompt
    assert PINNED_SPOT.isoformat() in prompt


def test_rule_based_baseline_honours_the_pin():
    with override_trade_date(PINNED_DAY):
        result = parse_rule_based("Buy 5 million norwegian kroner for usd spot at 10.2")
    assert result["instrument"]["settlement_date"] == PINNED_SPOT.isoformat()


async def test_frozen_rate_provider_replays_the_same_rate():
    provider = FrozenRateProvider.from_file()
    first = await provider(CurrencyPair.EURUSD)
    assert await provider(CurrencyPair.EURUSD) == first
    rate, as_of = first
    assert isinstance(rate, float)
    assert rate > 0
    assert isinstance(as_of, date)


def test_frozen_snapshot_covers_every_supported_pair():
    assert FrozenRateProvider.from_file().pairs == set(SUPPORTED_PAIRS)


async def test_frozen_rate_provider_refuses_an_unrecorded_pair():
    provider = FrozenRateProvider({})
    with pytest.raises(MissingFrozenRate):
        await provider(CurrencyPair.EURUSD)
    # Not a ValueError/RuntimeError, or the resolver would convert it into a
    # ParseError and the retry loop would report a broken harness as a model
    # that could not parse its input.
    assert not issubclass(MissingFrozenRate, (ValueError, RuntimeError))


async def test_missing_frozen_rate_is_not_reported_as_a_parse_failure():
    from app.services.nl_parse.clients import Completion

    content = dict(_VALID_SPOT_CONTENT)
    content["instrument"] = {"instrument_type": "SPOT", "rate": None}

    class FakeClient:
        async def complete_json(self, messages):
            return Completion(content=content, usage={})

    with override_trade_date(PINNED_DAY):
        with patch("app.services.nl_parse.parser.get_client", return_value=FakeClient()):
            with pytest.raises(MissingFrozenRate):
                await parse_trade(
                    "Buy EURUSD spot",
                    model_id="llama3.2:3b",
                    rate_provider=FrozenRateProvider({}),
                )
