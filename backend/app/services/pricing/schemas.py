"""Pydantic models for FX option pricing results."""

from datetime import date
from typing import Literal

from pydantic import BaseModel


class OptionGreeks(BaseModel):
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float


class OptionPriceResult(BaseModel):
    """Output of pricing a single FX option trade."""

    option_type: Literal["CALL", "PUT"]
    premium: float
    premium_currency: str
    spot: float
    strike_rate: float
    valuation_date: date
    expiry_date: date
    tenor_years: float
    vol: float
    domestic_rate: float
    foreign_rate: float
    greeks: OptionGreeks
