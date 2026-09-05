import uuid
from datetime import date, datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_serializer, model_validator

from app.models.enums import InstrumentType, CurrencyPair, Direction, Currency, TradeStatus, TradeState
from app.schemas.instrument_details import InstrumentDetails
from app.services.business_calendar import (
    effective_trade_date,
    is_business_day,
    spot_value_date,
)


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

    @model_validator(mode="after")
    def check_settlement_within_spot_window(self):
        # trade_date is server-assigned at booking time to the effective trade
        # date (today, rolled forward to a business day), so the spot window is
        # anchored on the same date.
        if self.instrument_type == InstrumentType.OPTION:
            return self  # options use delivery_date, not settlement_date
        trade_date = effective_trade_date(date.today())
        spot = spot_value_date(trade_date)
        settlement = self.instrument_details.settlement_date
        if not is_business_day(settlement):
            raise ValueError("settlement_date must be a business day (Mon-Fri)")
        if self.instrument_type == InstrumentType.SPOT:
            if not (trade_date <= settlement <= spot):
                raise ValueError(
                    f"SPOT settlement_date must be between {trade_date} and {spot} "
                    f"(trade date + 2 business days); use FORWARD for later dates"
                )
        else:  # FORWARD
            if settlement <= spot:
                raise ValueError(
                    f"FORWARD settlement_date must be after {spot} "
                    f"(trade date + 2 business days)"
                )
        return self


class TradeCancelRequest(BaseModel):
    comment: Optional[str] = None


class TradeAmendRequest(BaseModel):
    # instrument_type is structural (it selects the details schema) and cannot be
    # changed via an amend; the other trade fields may all be edited.
    currency_pair: Optional[CurrencyPair] = None
    direction: Optional[Direction] = None
    counterparty: Optional[str] = None
    notional_1: Optional[float] = None
    notional_2: Optional[float] = None
    instrument_details: Optional[InstrumentDetails] = None
    comment: Optional[str] = None

    @model_validator(mode="after")
    def require_at_least_one_change(self):
        if all(
            field is None
            for field in (
                self.currency_pair,
                self.direction,
                self.counterparty,
                self.notional_1,
                self.notional_2,
                self.instrument_details,
                self.comment,
            )
        ):
            raise ValueError(
                "amend requires at least one of currency_pair, direction, "
                "counterparty, notional_1, notional_2, instrument_details or comment"
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

    @field_serializer("changed_at")
    def _serialize_changed_at(self, value: datetime) -> str:
        # ISO 8601 UTC with Z suffix, per docs/api_contracts.md
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TradeHistoryRead(BaseModel):
    trade_id: uuid.UUID
    history: list[TradeStateRead]