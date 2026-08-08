import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.enums import InstrumentType, CurrencyPair, Direction, Currency, TradeStatus, TradeState
from app.schemas.instrument_details import InstrumentDetails


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
    instrument_details: InstrumentDetails

    @model_validator(mode="after")
    def check_instrument_type_matches(self):
        if self.instrument_details.instrument_type != self.instrument_type.value:
            raise ValueError(
                f"instrument_details.instrument_type ({self.instrument_details.instrument_type}) "
                f"does not match instrument_type ({self.instrument_type.value})"
            )
        return self


class TradeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trade_id: uuid.UUID
    instrument_type: InstrumentType
    currency_pair: CurrencyPair
    direction: Direction
    currency_1: Currency
    notional_1: float
    currency_2: Currency
    notional_2: Optional[float] = None
    trade_date: date
    counterparty: str
    status: TradeStatus
    comment: Optional[str] = None
    instrument_details: InstrumentDetails


class TradeStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    state_id: int
    trade_id: uuid.UUID
    state: TradeState
    changed_at: datetime
    changed_by: str
    notes: Optional[str] = None