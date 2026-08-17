"""Append-only lifecycle log for trades.

Every state transition a trade goes through is recorded as an immutable row
in the ``trade_state`` table so the full history is always available and can
never be rewritten (append-only by design).
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TradeState, TradeStatus
from app.models.trade import Trade
from app.models.trade_state import TradeStateLog


async def append_state(
    db: AsyncSession,
    trade_id: UUID,
    state: TradeState,
    changed_by: str = "system",
    notes: str | None = None,
) -> TradeStateLog:
    """Append a state transition to a trade's lifecycle log.

    The row is added but *not* committed, so callers can combine it with
    their own changes (e.g. the trade update) in a single transaction.
    """
    entry = TradeStateLog(
        trade_id=trade_id,
        state=state,
        changed_at=datetime.now(timezone.utc),
        changed_by=changed_by,
        notes=notes,
    )
    db.add(entry)
    return entry


async def cancel_trade(
    db: AsyncSession,
    trade: Trade,
    changed_by: str = "system",
    notes: str | None = None,
) -> TradeStateLog:
    """Cancel a trade: `status` becomes CANCELLED and a log entry is appended.

    The trade row is never deleted — only its state changes. Raises
    ``ValueError`` if the trade is not in a cancellable state.
    """
    if trade.status not in (
        TradeStatus.PENDING_CONFIRMATION,
        TradeStatus.BOOKED,
    ):
        raise ValueError(
            f"trade {trade.trade_id} in state {trade.status.value} cannot be cancelled"
        )
    trade.status = TradeStatus.CANCELLED
    return await append_state(
        db, trade.trade_id, TradeState.CANCELLED, changed_by, notes
    )


async def amend_trade(
    db: AsyncSession,
    trade: Trade,
    changed_by: str = "system",
    notes: str | None = None,
) -> TradeStateLog:
    """Amend a booked trade: `status` stays BOOKED and an AMENDED entry is logged.

    Raises ``ValueError`` if the trade is not BOOKED.
    """
    if trade.status != TradeStatus.BOOKED:
        raise ValueError(
            f"trade {trade.trade_id} in state {trade.status.value} cannot be amended"
        )
    return await append_state(db, trade.trade_id, TradeState.AMENDED, changed_by, notes)


async def confirm_trade(
    db: AsyncSession,
    trade: Trade,
    changed_by: str = "system",
    notes: str | None = None,
) -> TradeStateLog:
    """Confirm a pending trade: `status` becomes BOOKED and a log entry is appended.

    Raises ``ValueError`` if the trade is not PENDING_CONFIRMATION.
    """
    if trade.status != TradeStatus.PENDING_CONFIRMATION:
        raise ValueError(
            f"trade {trade.trade_id} in state {trade.status.value} cannot be confirmed"
        )
    trade.status = TradeStatus.BOOKED
    return await append_state(db, trade.trade_id, TradeState.BOOKED, changed_by, notes)

