"""Orchestration: natural language -> validated TradeCreate via a selectable model."""

import json
from dataclasses import dataclass
from datetime import date

from pydantic import ValidationError

from app.core.config import settings
from app.models.enums import Currency, CurrencyPair, Direction, InstrumentType
from app.schemas.instrument_details import ForwardDetails, OptionDetails, SpotDetails
from app.schemas.trade import TradeCreate
from app.services.business_calendar import add_business_days, effective_trade_date, spot_value_date
from app.services.market_data.frankfurter_client import get_rate
from app.services.nl_parse.baseline import ParseError
from app.services.nl_parse.clients import get_client
from app.services.nl_parse.models import get_model_info
from app.services.nl_parse.prompts import build_messages
from app.services.nl_parse.schemas import NLTradeDraft


@dataclass
class ParseResult:
    draft: NLTradeDraft
    trade: TradeCreate
    model: str
    raw: dict | None


async def draft_to_trade_create(draft: NLTradeDraft) -> TradeCreate:
    """Map a parsed draft onto the real TradeCreate schema.

    Missing rates are resolved from the live market rate and missing option
    fields get sensible defaults, then the standard validators run
    (instrument-type match, settlement window, business days, ...).
    """
    pair = draft.currency_pair
    currency_1, currency_2 = pair[:3], pair[3:]
    inst = draft.instrument
    today = effective_trade_date(date.today())

    if inst.instrument_type == "OPTION":
        if inst.expiry_date is None:
            raise ParseError("option is missing an expiry date")
        details = OptionDetails(
            instrument_type="OPTION",
            option_type=inst.option_type or "CALL",
            strike_rate=inst.strike_rate if inst.strike_rate is not None else 1.0,
            premium_date=inst.premium_date or spot_value_date(today),
            expiry_date=inst.expiry_date,
            delivery_date=inst.delivery_date or inst.expiry_date,
            premium=inst.premium if inst.premium is not None else 0.0,
            premium_currency=inst.premium_currency or currency_2,
            exercise_style=inst.exercise_style or "EUROPEAN",
        )
    else:
        rate = inst.rate
        if rate is None:
            try:
                rate, _ = await get_rate(CurrencyPair[pair])
            except (RuntimeError, KeyError) as exc:
                raise ParseError(f"market rate unavailable for {pair}") from exc
        settlement = inst.settlement_date or (
            spot_value_date(today)
            if inst.instrument_type == "SPOT"
            else add_business_days(today, 20)
        )
        details_cls = SpotDetails if inst.instrument_type == "SPOT" else ForwardDetails
        details = details_cls(
            instrument_type=inst.instrument_type,
            rate=rate,
            settlement_date=settlement,
        )

    try:
        return TradeCreate(
            instrument_type=InstrumentType[inst.instrument_type],
            currency_pair=CurrencyPair[pair],
            direction=Direction[draft.direction],
            currency_1=Currency[currency_1],
            notional_1=draft.notional_1,
            currency_2=Currency[currency_2],
            counterparty=draft.counterparty or "BANK_A",
            comment=draft.comment,
            instrument_details=details,
        )
    except ValidationError as exc:
        raise ParseError(
            "parsed trade failed validation: " + "; ".join(e["msg"] for e in exc.errors())
        ) from exc


async def parse_trade(text: str, model_id: str | None = None) -> ParseResult:
    """Parse ``text`` with the selected model and return a validated trade."""
    model_id = model_id or settings.nl_parse_default_model
    info = get_model_info(model_id)
    client = get_client(info)

    messages = build_messages(text)
    system = messages[0]["content"]
    user = text
    last_error: Exception | None = None

    for attempt in range(2):
        try:
            raw = await client.complete_json(system, user)
            draft = NLTradeDraft.model_validate(raw)
            trade = await draft_to_trade_create(draft)
            return ParseResult(draft=draft, trade=trade, model=info.id, raw=raw)
        except (ValidationError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt == 0 and info.kind != "baseline":
                user = (
                    f"{text}\n\nYour previous output was invalid ({exc}).\n"
                    "Return ONLY valid JSON matching the schema."
                )
                continue
            break

    raise ParseError(f"model {model_id} could not parse input: {last_error}")
