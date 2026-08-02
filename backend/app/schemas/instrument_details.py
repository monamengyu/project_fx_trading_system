from datetime import date
from typing import Literal, Union

from pydantic import BaseModel


class SpotDetails(BaseModel):
    rate: float
    settlement_date: date


class ForwardDetails(BaseModel):
    rate: float
    settlement_date: date


class OptionDetails(BaseModel):
    option_type: Literal["CALL", "PUT"]
    strike_rate: float
    premium_date: date
    expiry_date: date
    delivery_date: date
    premium: float
    premium_currency: str
    exercise_style: Literal["EUROPEAN", "AMERICAN"]


InstrumentDetails = Union[SpotDetails, ForwardDetails, OptionDetails]