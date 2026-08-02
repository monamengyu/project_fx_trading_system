import uuid
from datetime import date
from typing import Optional

from sqlalchemy import String, Text, Numeric, Date, Enum as SAEnum, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import InstrumentType, CurrencyPair, Direction, Currency, TradeStatus
from app.schemas.instrument_details import validate_instrument_details

from pydantic import BaseModel, field_validator

class Trade(Base):
    __tablename__ = "trades"

    # check if JSONB contain rate or strike_rate
    __table_args__ = (
        CheckConstraint(
            "instrument_details ? 'rate' OR instrument_details ? 'strike_rate'",
            name="check_instrument_details_has_required_keys"
        ),
    )

    trade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    instrument_type: Mapped[InstrumentType] = mapped_column(SAEnum(InstrumentType))
    currency_pair: Mapped[CurrencyPair] = mapped_column(SAEnum(CurrencyPair))
    direction: Mapped[Direction] = mapped_column(SAEnum(Direction))
    currency_1: Mapped[Currency] = mapped_column(SAEnum(Currency))
    notional_1: Mapped[float] = mapped_column(Numeric(18, 2))
    currency_2: Mapped[Currency] = mapped_column(SAEnum(Currency))
    notional_2: Mapped[float] = mapped_column(Numeric(18, 2), nullable=True)
    trade_date: Mapped[date] = mapped_column(Date)
    counterparty: Mapped[str] = mapped_column(String(100))
    status: Mapped[TradeStatus] = mapped_column(SAEnum(TradeStatus))
    comment: Mapped[str] = mapped_column(Text, nullable=True)
    instrument_details: Mapped[dict] = mapped_column(JSONB)

    states: Mapped[list["TradeStateLog"]] = relationship(
        back_populates="trade", cascade="all, delete-orphan"
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
    instrument_details: dict

    @field_validator("instrument_details")
    @classmethod
    def check_instrument_details(cls, value, info):
        instrument_type = info.data.get("instrument_type")
        if instrument_type is not None:
            validate_instrument_details(instrument_type.value, value)
        return value