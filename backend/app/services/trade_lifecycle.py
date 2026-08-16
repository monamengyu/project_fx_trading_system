"""Append-only lifecycle log for trades.

Every state transition a trade goes through is recorded as an immutable row
in the ``trade_state`` table so the full history is always available and can
never be rewritten (append-only by design).
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TradeState
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
