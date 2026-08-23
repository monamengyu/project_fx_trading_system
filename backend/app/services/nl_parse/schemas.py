"""Structured output contract for NL trade parsing.

An LLM (or the rule-based baseline) returns JSON matching ``NLTradeDraft``.
We then resolve it through the real ``TradeCreate`` schema so every existing
validation rule (instrument-type match, settlement window, business days, ...)
applies unchanged.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class ParsedInstrument(BaseModel):
    instrument_type: Literal["SPOT", "FORWARD", "OPTION"]

    # SPOT / FORWARD
    rate: float | None = None
    settlement_date: date | None = None

    # OPTION
    option_type: Literal["CALL", "PUT"] | None = None
    strike_rate: float | None = None
    expiry_date: date | None = None
    delivery_date: date | None = None
    premium_date: date | None = None
    premium: float | None = None
    premium_currency: str | None = None
    exercise_style: Literal["EUROPEAN", "AMERICAN"] | None = None


class NLTradeDraft(BaseModel):
    """A normalised trade described in natural language."""

    instrument_type: Literal["SPOT", "FORWARD", "OPTION"]
    currency_pair: str = Field(pattern=r"^[A-Z]{6}$")
    direction: Literal["BUY", "SELL"]
    notional_1: float = Field(gt=0)
    counterparty: str | None = None
    comment: str | None = None
    instrument: ParsedInstrument
