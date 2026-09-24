"""Engineered prompts for converting natural language into a structured trade."""

from datetime import date

from app.services.business_calendar import (
    add_months,
    current_trade_date,
    option_delivery_date,
    spot_value_date,
)
from app.services.market_data.pairs import SUPPORTED_PAIRS

SYSTEM_PROMPT = """You are an FX trade desk assistant. A trader's instruction either states a bookable trade or it does not. Respond with ONLY valid JSON — no prose, no markdown, no code fences.

Supported currency pairs: {pairs}.
Direction: BUY (buy the first currency, sell the second) or SELL (the opposite).
Counterparty must be one of: BANK_A, BANK_B, BANK_C. Default to BANK_A when unspecified.

Instruments:
- SPOT: settles on the spot value date, today + 2 business days (weekends excluded).
- FORWARD: settles a stated tenor after the spot value date.
- OPTION: has option_type (CALL/PUT), strike_rate, expiry_date, delivery_date (expiry + 2 business days), premium_date, premium, premium_currency, exercise_style (EUROPEAN or AMERICAN).

Today is {today}. The spot value date (today + 2 business days) is {spot}.

Output a trade only when the instruction states one. When it does not, decline. Never invent, guess or default a value to make an instruction fit: a booked trade with an invented field is worse than a refusal.

JSON schema — for a bookable trade, output exactly this shape, all keys present; use null for fields that do not apply:
{{
  "instrument_type": "SPOT" | "FORWARD" | "OPTION",
  "currency_pair": {pair_union},
  "direction": "BUY" | "SELL",
  "notional_1": <number>,
  "counterparty": "BANK_A" | "BANK_B" | "BANK_C",
  "comment": <string or null>,
  "instrument": {{
    "instrument_type": <same as top level>,
    "rate": <number or null>,
    "settlement_date": "YYYY-MM-DD" or null,
    "option_type": "CALL" | "PUT" or null,
    "strike_rate": <number or null>,
    "expiry_date": "YYYY-MM-DD" or null,
    "delivery_date": "YYYY-MM-DD" or null,
    "premium_date": "YYYY-MM-DD" or null,
    "premium": <number or null>,
    "premium_currency": <string or null>,
    "exercise_style": "EUROPEAN" | "AMERICAN" or null
  }}
}}

To decline, output exactly this and nothing else:
{{"error": "<what the instruction is missing or what is wrong with it>"}}

Rules:
- Settlement/expiry dates must be business days (Mon-Fri).
- A SPOT settlement_date is {spot}; later dates must be FORWARD.
- A stated tenor counts from {spot}, not from today: a 3-month forward settles three months after {spot}, and a 3-month option expires three months after {spot}.
- An option's delivery_date is two business days after its expiry_date.
- Do NOT output currency_2 — it is derived from the pair.
- If a rate is not stated, leave it null (the system fills the market rate).
- Decline when the instruction cannot be booked as stated: no currency pair, or a pair outside the supported list; no direction; a notional that is missing, not positive, or vague ("a few million"); an option with no expiry; a forward settling on or before {spot}.
- An unusual but complete instruction is still bookable: book it, with your best reading of the wording.
"""

#: Every demonstration states its dates the familiar way, whether by spelling them
#: out or by naming a tenor. A shifted spelling is deliberately never demonstrated:
#: the shifted arm is the thing that measures reading one for the first time.
def _instrument(**stated) -> dict:
    """One demonstration's instrument block, every key present as the schema asks."""
    return {
        "instrument_type": None,
        "rate": None,
        "settlement_date": None,
        "option_type": None,
        "strike_rate": None,
        "expiry_date": None,
        "delivery_date": None,
        "premium_date": None,
        "premium": None,
        "premium_currency": None,
        "exercise_style": None,
        **stated,
    }


def _few_shots(today: date) -> list[tuple[str, dict]]:
    """The demonstrations, dated against ``today``.

    A date the sentence spells out is literal. The ones a convention fixes -- a
    spot settlement, a tenor, an option delivery -- are computed, so a
    demonstration still shows the right answer on any day it is replayed rather
    than only on the day it was written.
    """
    spot = spot_value_date(today)
    three_months = add_months(spot, 3)
    return [
        (
            "Buy 1 million euros against dollars, spot",
            {
                "instrument_type": "SPOT",
                "currency_pair": "EURUSD",
                "direction": "BUY",
                "notional_1": 1000000,
                "counterparty": "BANK_A",
                "comment": None,
                "instrument": _instrument(
                    instrument_type="SPOT",
                    settlement_date=spot.isoformat(),
                ),
            },
        ),
        (
            "Sell 500k GBP for USD settling 2026-11-30 at 1.27",
            {
                "instrument_type": "FORWARD",
                "currency_pair": "GBPUSD",
                "direction": "SELL",
                "notional_1": 500000,
                "counterparty": "BANK_A",
                "comment": None,
                "instrument": _instrument(
                    instrument_type="FORWARD",
                    rate=1.27,
                    settlement_date="2026-11-30",
                ),
            },
        ),
        (
            "Buy 3 million euros against dollars, forward in 3 months",
            {
                "instrument_type": "FORWARD",
                "currency_pair": "EURUSD",
                "direction": "BUY",
                "notional_1": 3000000,
                "counterparty": "BANK_A",
                "comment": None,
                "instrument": _instrument(
                    instrument_type="FORWARD",
                    settlement_date=three_months.isoformat(),
                ),
            },
        ),
        (
            "Buy a European call on EURUSD, strike 1.10, expiry 2026-12-18, notional 500k, premium 25000 USD",
            {
                "instrument_type": "OPTION",
                "currency_pair": "EURUSD",
                "direction": "BUY",
                "notional_1": 500000,
                "counterparty": "BANK_A",
                "comment": None,
                "instrument": _instrument(
                    instrument_type="OPTION",
                    option_type="CALL",
                    strike_rate=1.10,
                    expiry_date="2026-12-18",
                    delivery_date=option_delivery_date(date(2026, 12, 18)).isoformat(),
                    premium=25000,
                    premium_currency="USD",
                    exercise_style="EUROPEAN",
                ),
            },
        ),
        (
            "Sell 2 million euros against dollars, put strike of 1.0800 expiring in 3 months premium of 20000 EUR",
            {
                "instrument_type": "OPTION",
                "currency_pair": "EURUSD",
                "direction": "SELL",
                "notional_1": 2000000,
                "counterparty": "BANK_A",
                "comment": None,
                "instrument": _instrument(
                    instrument_type="OPTION",
                    option_type="PUT",
                    strike_rate=1.08,
                    expiry_date=three_months.isoformat(),
                    delivery_date=option_delivery_date(three_months).isoformat(),
                    premium=20000,
                    premium_currency="EUR",
                    exercise_style="EUROPEAN",
                ),
            },
        ),
        (
            "Sell a couple of million euros against dollars, spot",
            {"error": "the notional is vague: no definite amount is stated"},
        ),
    ]


def build_system_prompt(today: date | None = None) -> str:
    today = today or current_trade_date()
    spot = spot_value_date(today)
    return SYSTEM_PROMPT.format(
        today=today.isoformat(),
        spot=spot.isoformat(),
        pairs=", ".join(SUPPORTED_PAIRS),
        pair_union=" | ".join(f'"{pair}"' for pair in SUPPORTED_PAIRS),
    )


def build_messages(user_text: str) -> list[dict]:
    """system + few-shot demonstrations + the user instruction."""
    messages = [{"role": "system", "content": build_system_prompt()}]
    for example_text, example_json in _few_shots(current_trade_date()):
        messages.append({"role": "user", "content": example_text})
        messages.append({"role": "assistant", "content": _dump_json(example_json)})
    messages.append({"role": "user", "content": user_text})
    return messages


def _dump_json(obj: dict) -> str:
    import json

    return json.dumps(obj)
