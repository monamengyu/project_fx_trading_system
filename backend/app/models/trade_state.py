import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import TradeState


class TradeStateLog(Base):
    __tablename__ = "trade_state"

    state_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trades.trade_id"), nullable=False
    )
    state: Mapped[TradeState] = mapped_column(SAEnum(TradeState))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    changed_by: Mapped[str] = mapped_column(String(100))
    notes: Mapped[str] = mapped_column(Text, nullable=True)

    trade: Mapped["Trade"] = relationship(back_populates="states")