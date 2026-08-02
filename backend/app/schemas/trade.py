from datetime import date
from typing import Optional

from pydantic import BaseModel, field_validator

from app.models.enums import InstrumentType, CurrencyPair, Direction, Currency, TradeStatus
from app.schemas.instrument_details import validate_instrument_details


class TradeCreate(BaseModel):
    instrument_type: InstrumentType
    currency_pair: CurrencyPair
    direction: Direction
    currency_1: Currency
    notional_1: float
    currency_2: Currency
    notional_2: Optional[float] = None
    counterparty: str
    comment: Optional[str] = None
    instrument_details: dict

    @field_validator("instrument_details")
    @classmethod
    def check_instrument_details(cls, value, info):
        instrument_type = info.data.get("instrument_type")
        if instrument_type is not None:
            validate_instrument_details(instrument_type.value, value)
        return value