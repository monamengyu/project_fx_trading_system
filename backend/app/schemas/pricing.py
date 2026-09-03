"""Request/response models for the pricing REST endpoint."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import CurrencyPair
from app.services.pricing.schemas import OptionGreeks


class OptionQuoteRequest(BaseModel):
    """Live quote for an FX option built from raw trade terms."""

    currency_pair: CurrencyPair
    option_type: Literal["CALL", "PUT"]
    strike_rate: float = Field(gt=0)
    expiry_date: date
    notional_1: float = Field(gt=0)
    vol: float = Field(default=0.10, gt=0)


class OptionQuoteResponse(BaseModel):
    """Quote result for an FX option.

    ``premium`` is the per-unit premium in the quote currency (``currency_2``,
    e.g. USD for EURUSD). ``total_premium`` is the full premium for the quoted
    notional, i.e. ``notional_1 * premium``, also in ``premium_currency``.
    """

    currency_pair: str
    option_type: Literal["CALL", "PUT"]
    premium: float
    premium_currency: str
    total_premium: float
    spot: float
    strike_rate: float
    expiry_date: date
    valuation_date: date
    tenor_years: float
    vol: float
    greeks: OptionGreeks
