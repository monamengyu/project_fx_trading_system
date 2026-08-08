from datetime import date
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class SpotDetails(BaseModel):
    instrument_type: Literal["SPOT"]
    rate: float
    settlement_date: date


class ForwardDetails(BaseModel):
    instrument_type: Literal["FORWARD"]
    rate: float
    settlement_date: date


class OptionDetails(BaseModel):
    instrument_type: Literal["OPTION"]
    option_type: Literal["CALL", "PUT"]
    strike_rate: float
    premium_date: date
    expiry_date: date
    delivery_date: date
    premium: float
    premium_currency: str
    exercise_style: Literal["EUROPEAN", "AMERICAN"]


InstrumentDetails = Annotated[
    Union[SpotDetails, ForwardDetails, OptionDetails],
    Field(discriminator="instrument_type"),
]