"""Deterministic rule-based NL parser — the evaluation baseline.

Supports common phrasings for SPOT / FORWARD / OPTION trades. It is
intentionally simple: anything it cannot confidently map yields a ``ParseError``
so the evaluation can score it as a miss.
"""

import re
from datetime import date

from app.services.business_calendar import (
    add_business_days,
    current_trade_date,
    effective_trade_date,
    spot_value_date,
)
from app.services.market_data.pairs import SUPPORTED_PAIRS

# Spoken/alternative names per currency code, used to recognise pairs in free
# text ("euros against dollars", "sell gbp for usd", "kiwi vs usd", ...).
# Longer alternatives are listed first so alternation prefers the specific
# reading (e.g. "swiss francs" before "francs").
_CURRENCY_WORDS: dict[str, list[str]] = {
    "EUR": [r"euros?", r"eur"],
    "GBP": [r"pounds?", r"sterling", r"gbp"],
    "USD": [r"dollars?", r"bucks?", r"usd"],
    "JPY": [r"yen", r"jpy"],
    "CHF": [r"swiss francs?", r"francs?", r"chf"],
    "CAD": [r"canadian dollars?", r"loonies?", r"cad"],
    "AUD": [r"aussie dollars?", r"aussies?", r"australian dollars?", r"aud"],
    "NZD": [r"k(i)?wis?", r"new zealand dollars?", r"nzd"],
    "CNH": [r"yuan", r"renminbi", r"cnh"],
    "HKD": [r"hong kong dollars?", r"hkd"],
    "SGD": [r"singapore dollars?", r"sing dollars?", r"sgd"],
    "SEK": [r"swedish krona", r"kronas?", r"kronor", r"sek"],
    "NOK": [r"norwegian kroner", r"kroner", r"nok"],
    "MXN": [r"mexican pesos?", r"pesos?", r"mxn"],
    "ZAR": [r"south african rand", r"rand", r"zar"],
    "TRY": [r"turkish lira", r"lira", r"try"],
}

_CONNECTOR = r"(?:again(?:st)?|vs\.?|to|for)"

_PAIR_PATTERNS = []


def _word_group(code: str) -> str:
    """Alternation group matching any name for ``code`` (e.g. usd/dollars)."""
    return "(?:" + "|".join(_CURRENCY_WORDS[code]) + ")"


def _build_pair_patterns() -> list[tuple[re.Pattern, str]]:
    """Compile one matcher per supported pair, mirroring the code and spoken forms."""
    patterns: list[tuple[re.Pattern, str]] = []
    for pair in SUPPORTED_PAIRS:
        base, quote = pair[:3], pair[3:]
        base_group, quote_group = _word_group(base), _word_group(quote)
        code_form = (
            rf"\b{pair.lower()}\b|\b{base.lower()}/{quote.lower()}\b|"
            rf"\b{base.lower()}\s*/\s*{quote.lower()}\b"
        )
        spoken = (
            rf"\b{base_group}\s+{_CONNECTOR}\s+{quote_group}\b|"
            rf"\b{quote_group}\s+{_CONNECTOR}\s+{base_group}\b"
        )
        patterns.append((re.compile(rf"{code_form}|{spoken}"), pair))
    return patterns


_PAIR_PATTERNS = _build_pair_patterns()

_COUNTERPARTY = re.compile(r"\b(BANK_[ABC])\b")
_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_RATE = re.compile(r"\b(?:at|rate)\s+(?:of\s+)?(\d+(?:\.\d+)?)\b")
_STRIKE = re.compile(r"\bstrike(?:\s+rate)?\s+(?:of\s+)?(\d+(?:\.\d+)?)\b")
_PREMIUM = re.compile(r"\bpremium(?:\s+of)?\s+(\d+(?:\.\d+)?)(?:\s*([A-Z]{3}))?")
_NOTIONAL_SUFFIX = re.compile(
    r"([\d][\d,]*(?:\.\d+)?)\s*(million|m|k|thousand)\b", re.I
)
_NOTIONAL_WORD = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s+(million|thousand)\b",
    re.I,
)
_BARE_LARGE = re.compile(r"\b(\d[\d,]{4,}(?:\.\d+)?)\b")  # >= 10,000
_TENOR = re.compile(r"\bin\s+(\d+)\s+(week|weeks|month|months)\b", re.I)

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_SUFFIX_MULT = {"million": 1_000_000, "m": 1_000_000, "k": 1_000, "thousand": 1_000}


class ParseError(ValueError):
    pass


def _find_pair(text: str) -> str | None:
    for pattern, pair in _PAIR_PATTERNS:
        if pattern.search(text):
            return pair
    return None


def _notional(text: str) -> float | None:
    m = _NOTIONAL_SUFFIX.search(text)
    if m:
        value = float(m.group(1).replace(",", ""))
        return value * _SUFFIX_MULT[m.group(2).lower()]
    m = _NOTIONAL_WORD.search(text)
    if m:
        return _NUMBER_WORDS[m.group(1).lower()] * (
            1_000_000 if m.group(2).lower() == "million" else 1_000
        )
    m = _BARE_LARGE.search(text)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def _date_near(text: str, keyword: str) -> date | None:
    m = re.search(keyword + r"[\s:]+\d{4}-\d{2}-\d{2}", text, re.I)
    if m:
        return date.fromisoformat(re.search(r"\d{4}-\d{2}-\d{2}", m.group(0)).group(0))
    return None


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(d.day, 28))


def _tenor_settlement(text: str) -> date | None:
    m = _TENOR.search(text)
    if not m:
        return None
    count = int(m.group(1))
    unit = m.group(2).lower()
    base = current_trade_date()
    if unit.startswith("month"):
        return effective_trade_date(_add_months(base, count))
    return effective_trade_date(base + __import__("datetime").timedelta(days=7 * count))


def _option_settlement(text: str) -> date | None:
    return _date_near(text, r"settl(e|ing|ement)?")


def parse_rule_based(text: str) -> dict:
    lower = text.lower()

    pair = _find_pair(lower)
    if pair is None:
        raise ParseError("could not determine currency pair")
    currency_2 = pair[3:]

    direction = None
    if re.search(r"\bsell\b", lower):
        direction = "SELL"
    elif re.search(r"\bbuy\b", lower):
        direction = "BUY"
    if direction is None:
        raise ParseError("could not determine direction (buy/sell)")

    notional = _notional(text)
    if notional is None:
        raise ParseError("could not determine notional")

    counterparty_m = _COUNTERPARTY.search(text)
    counterparty = counterparty_m.group(1) if counterparty_m else None

    comment = None

    if re.search(r"\b(call|put)\b", lower):
        instrument_type = "OPTION"
        option_type = "CALL" if re.search(r"\bcall\b", lower) else "PUT"
        strike_m = _STRIKE.search(lower) or _RATE.search(lower)
        strike = float(strike_m.group(1)) if strike_m else None
        premium_m = _PREMIUM.search(text)
        premium = float(premium_m.group(1)) if premium_m else None
        premium_currency = premium_m.group(2) if premium_m and premium_m.group(2) else currency_2
        expiry = _date_near(lower, r"expir(?:e|ing|y|es)?") or _DATE.search(text)
        expiry_date = expiry if isinstance(expiry, date) else None
        if expiry_date is None:
            raise ParseError("option is missing an expiry date")
        exercise_style = (
            "EUROPEAN" if re.search(r"\beuropean\b", lower)
            else "AMERICAN" if re.search(r"\bamerican\b", lower)
            else None
        )
        instrument = {
            "instrument_type": "OPTION",
            "rate": None,
            "settlement_date": None,
            "option_type": option_type,
            "strike_rate": strike,
            "expiry_date": expiry_date.isoformat(),
            "delivery_date": None,
            "premium_date": None,
            "premium": premium,
            "premium_currency": premium_currency,
            "exercise_style": exercise_style,
        }
    else:
        explicit_settlement = _option_settlement(text)
        tenor_settlement = _tenor_settlement(text)
        is_forward = (
            bool(re.search(r"\b(forward|future)\b", lower))
            or explicit_settlement is not None
            or tenor_settlement is not None
        )
        if is_forward:
            instrument_type = "FORWARD"
            settlement = (
                explicit_settlement
                or tenor_settlement
                or effective_trade_date(_add_months(current_trade_date(), 1))
            )
        else:
            instrument_type = "SPOT"
            settlement = spot_value_date(current_trade_date())
        rate_m = _RATE.search(lower)
        rate = float(rate_m.group(1)) if rate_m else None
        instrument = {
            "instrument_type": instrument_type,
            "rate": rate,
            "settlement_date": settlement.isoformat(),
            "option_type": None,
            "strike_rate": None,
            "expiry_date": None,
            "delivery_date": None,
            "premium_date": None,
            "premium": None,
            "premium_currency": None,
            "exercise_style": None,
        }

    return {
        "instrument_type": instrument_type,
        "currency_pair": pair,
        "direction": direction,
        "notional_1": notional,
        "counterparty": counterparty,
        "comment": comment,
        "instrument": instrument,
    }
