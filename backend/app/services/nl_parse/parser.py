"""Orchestration: natural language -> validated TradeCreate via a selectable model."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date

from pydantic import ValidationError

from app.core.config import settings
from app.models.enums import Currency, CurrencyPair, Direction, InstrumentType
from app.schemas.instrument_details import ForwardDetails, OptionDetails, SpotDetails
from app.schemas.trade import TradeCreate
from app.services.business_calendar import (
    add_business_days,
    current_trade_date,
    spot_value_date,
)
from app.services.market_data.frankfurter_client import get_rate
from app.services.nl_parse.baseline import ParseError
from app.services.nl_parse.clients import get_client
from app.services.nl_parse.models import get_model_info
from app.services.nl_parse.prompts import build_messages
from app.services.nl_parse.schemas import NLTradeDraft


# Resolves a currency pair to ``(rate, as_of)``. Injectable so that an
# evaluation run can replay a frozen snapshot instead of reading the live market.
RateProvider = Callable[[CurrencyPair], Awaitable[tuple[float, date]]]

# Settlement convention for a forward whose draft does not state a date.
DEFAULT_FORWARD_TENOR_DAYS = 20


@dataclass
class ParseResult:
    draft: NLTradeDraft
    trade: TradeCreate
    model: str
    raw: dict | None
    usage: dict | None = None
    # Names of the fields the resolver invented because the draft left them
    # unspecified; empty means the model stated everything it was asked for.
    defaulted_fields: list[str] = field(default_factory=list)
    # The model the provider reported answering, when it reports one; ``None``
    # for the rule-based baseline. A gateway may route to a dated snapshot, so
    # this is what a run has to be attributed to.
    served_model: str | None = None


@dataclass
class ResolvedTrade:
    trade: TradeCreate
    defaulted_fields: list[str]


def _fill_if_none(value, fallback, name: str, defaulted: list[str]):
    """Use ``fallback`` when ``value`` is ``None``, recording that we did."""
    if value is None:
        defaulted.append(name)
        return fallback
    return value


def _fill_if_falsy(value, fallback, name: str, defaulted: list[str]):
    """Use ``fallback`` when ``value`` is falsy, recording that we did."""
    if not value:
        defaulted.append(name)
        return fallback
    return value


async def resolve_draft(
    draft: NLTradeDraft,
    *,
    rate_provider: RateProvider | None = None,
) -> ResolvedTrade:
    """Map a parsed draft onto the real TradeCreate schema.

    Missing rates are resolved from the market rate and missing option fields get
    sensible defaults, then the standard validators run (instrument-type match,
    settlement window, business days, ...).

    ``rate_provider`` exists for reproducibility: the default reads the live
    market, which makes a run impossible to replay because the same input can
    resolve to a different trade tomorrow. Evaluation runs pass a frozen
    snapshot instead. The trade date comes from ``current_trade_date``, which
    such a run pins with ``business_calendar.override_trade_date`` -- it is
    ambient rather than a parameter because ``TradeCreate``'s settlement-window
    validator has to read the same date and cannot receive one.

    Every value the resolver *invents* rather than *reads* is recorded in
    ``defaulted_fields``. A draft that needed four defaults is a much weaker
    parse than one that needed none, even when both validate into a well-formed
    trade, so the count is a usable confidence signal.
    """
    pair = draft.currency_pair
    currency_1, currency_2 = pair[:3], pair[3:]
    inst = draft.instrument
    today = current_trade_date()
    defaulted: list[str] = []

    if inst.instrument_type == "OPTION":
        if inst.expiry_date is None:
            raise ParseError("option is missing an expiry date")
        details = OptionDetails(
            instrument_type="OPTION",
            option_type=_fill_if_falsy(inst.option_type, "CALL", "option_type", defaulted),
            strike_rate=_fill_if_none(inst.strike_rate, 1.0, "strike_rate", defaulted),
            premium_date=_fill_if_falsy(
                inst.premium_date, spot_value_date(today), "premium_date", defaulted
            ),
            expiry_date=inst.expiry_date,
            delivery_date=_fill_if_falsy(
                inst.delivery_date, inst.expiry_date, "delivery_date", defaulted
            ),
            premium=_fill_if_none(inst.premium, 0.0, "premium", defaulted),
            premium_currency=_fill_if_falsy(
                inst.premium_currency, currency_2, "premium_currency", defaulted
            ),
            exercise_style=_fill_if_falsy(
                inst.exercise_style, "EUROPEAN", "exercise_style", defaulted
            ),
        )
    else:
        rate = inst.rate
        if rate is None:
            # Deliberately not recorded as defaulted: a spot/forward rate is
            # fixed by the market, so omitting it is a normal request rather
            # than a guess about what the trader meant.
            provider = rate_provider or get_rate
            try:
                rate, _ = await provider(CurrencyPair[pair])
            except (RuntimeError, KeyError) as exc:
                raise ParseError(f"market rate unavailable for {pair}") from exc
        settlement_fallback = (
            spot_value_date(today)
            if inst.instrument_type == "SPOT"
            else add_business_days(today, DEFAULT_FORWARD_TENOR_DAYS)
        )
        details_cls = SpotDetails if inst.instrument_type == "SPOT" else ForwardDetails
        details = details_cls(
            instrument_type=inst.instrument_type,
            rate=rate,
            settlement_date=_fill_if_falsy(
                inst.settlement_date, settlement_fallback, "settlement_date", defaulted
            ),
        )

    try:
        trade = TradeCreate(
            instrument_type=InstrumentType[inst.instrument_type],
            currency_pair=CurrencyPair[pair],
            direction=Direction[draft.direction],
            currency_1=Currency[currency_1],
            notional_1=draft.notional_1,
            currency_2=Currency[currency_2],
            counterparty=_fill_if_falsy(
                draft.counterparty, "BANK_A", "counterparty", defaulted
            ),
            comment=draft.comment,
            instrument_details=details,
        )
    except ValidationError as exc:
        raise ParseError(
            "parsed trade failed validation: " + "; ".join(e["msg"] for e in exc.errors())
        ) from exc

    return ResolvedTrade(trade=trade, defaulted_fields=defaulted)


async def draft_to_trade_create(draft: NLTradeDraft) -> TradeCreate:
    """Return just the validated trade; see ``resolve_draft`` for the details."""
    return (await resolve_draft(draft)).trade


async def parse_trade(
    text: str,
    model_id: str | None = None,
    *,
    rate_provider: RateProvider | None = None,
) -> ParseResult:
    """Parse ``text`` with the selected model and return a validated trade.

    ``rate_provider`` is forwarded to ``resolve_draft`` so a run can replay a
    frozen market; see that function for the rationale. Pin the trade date with
    ``business_calendar.override_trade_date``.
    """
    model_id = model_id or settings.nl_parse_default_model
    info = get_model_info(model_id)
    client = get_client(info)

    messages = build_messages(text)
    last_error: Exception | None = None
    usage: dict | None = None
    served_model: str | None = None

    for attempt in range(2):
        try:
            completion = await client.complete_json(messages)
            usage = _accumulate_usage(usage, completion.usage)
            served_model = completion.model or served_model
            draft = NLTradeDraft.model_validate(completion.content)
            resolved = await resolve_draft(draft, rate_provider=rate_provider)
            return ParseResult(
                draft=draft,
                trade=resolved.trade,
                model=info.id,
                raw=completion.content,
                usage=usage,
                defaulted_fields=resolved.defaulted_fields,
                served_model=served_model,
            )
        except (ValidationError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt == 0 and info.kind != "baseline":
                # The worked examples are kept; only the final turn changes.
                messages = [
                    *messages[:-1],
                    {
                        "role": "user",
                        "content": (
                            f"{text}\n\nYour previous output was invalid ({exc}).\n"
                            "Return ONLY valid JSON matching the schema."
                        ),
                    },
                ]
                continue
            break

    raise ParseError(f"model {model_id} could not parse input: {last_error}")


def _accumulate_usage(total: dict | None, current: dict | None) -> dict | None:
    """Merge a provider usage object into an accumulating total (token counts).

    LLM calls that fail validation and are retried still consume tokens, so
    usage is summed across all attempts rather than only reporting the last.
    """
    if not current:
        return total
    if total is None:
        return dict(current)
    merged = dict(total)
    for key, value in current.items():
        if isinstance(value, (int, float)):
            merged[key] = merged.get(key, 0) + value
        elif key not in merged:
            merged[key] = value
    return merged
