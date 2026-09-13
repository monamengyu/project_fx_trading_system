"""Engineered prompts for converting natural language into a structured trade."""

from datetime import date

from app.services.business_calendar import current_trade_date, spot_value_date
from app.services.market_data.pairs import SUPPORTED_PAIRS

SYSTEM_PROMPT = """You are an FX trade desk assistant. Convert a trader's natural-language instruction into a single structured JSON trade. Respond with ONLY valid JSON — no prose, no markdown, no code fences.

Supported currency pairs: {pairs}.
Direction: BUY (buy the first currency, sell the second) or SELL (the opposite).
Counterparty must be one of: BANK_A, BANK_B, BANK_C. Default to BANK_A when unspecified.

Instruments:
- SPOT: settles between today and today + 2 business days (weekends excluded).
- FORWARD: settles after today + 2 business days.
- OPTION: has option_type (CALL/PUT), strike_rate, expiry_date, delivery_date, premium_date, premium, premium_currency, exercise_style (EUROPEAN or AMERICAN).

Today is {today}. The spot value date (today + 2 business days) is {spot}.

JSON schema — output exactly this shape, all keys present; use null for fields that do not apply:
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

Rules:
- Settlement/expiry dates must be business days (Mon-Fri).
- For SPOT the settlement_date must be within [today, {spot}]; later dates must be FORWARD.
- Do NOT output currency_2 — it is derived from the pair.
- If a rate is not stated, leave it null (the system fills the market rate).
- If the instruction is ambiguous, output your single best interpretation.
"""

FEW_SHOT_EXAMPLES: list[tuple[str, dict]] = [
    (
        "Buy 1 million euros against dollars, spot",
        {
            "instrument_type": "SPOT",
            "currency_pair": "EURUSD",
            "direction": "BUY",
            "notional_1": 1000000,
            "counterparty": "BANK_A",
            "comment": None,
            "instrument": {
                "instrument_type": "SPOT",
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
            },
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
            "instrument": {
                "instrument_type": "FORWARD",
                "rate": 1.27,
                "settlement_date": "2026-11-30",
                "option_type": None,
                "strike_rate": None,
                "expiry_date": None,
                "delivery_date": None,
                "premium_date": None,
                "premium": None,
                "premium_currency": None,
                "exercise_style": None,
            },
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
            "instrument": {
                "instrument_type": "OPTION",
                "rate": None,
                "settlement_date": None,
                "option_type": "CALL",
                "strike_rate": 1.10,
                "expiry_date": "2026-12-18",
                "delivery_date": None,
                "premium_date": None,
                "premium": 25000,
                "premium_currency": "USD",
                "exercise_style": "EUROPEAN",
            },
        },
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
    for example_text, example_json in FEW_SHOT_EXAMPLES:
        messages.append({"role": "user", "content": example_text})
        messages.append({"role": "assistant", "content": _dump_json(example_json)})
    messages.append({"role": "user", "content": user_text})
    return messages


def _dump_json(obj: dict) -> str:
    import json

    return json.dumps(obj)
