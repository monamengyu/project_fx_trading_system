"""Shared setup for the backend tests.

``GET /positions`` aggregates every BOOKED trade in the database, and the tests
assert on the whole book rather than on the trades they booked. A trade left behind
by the dashboard, by a manual call to the API or by a run that died before its
cleanup then changes what the next test sees. Every test starts from an empty book
instead.

The wipe runs against whatever ``DATABASE_URL`` points at: the throwaway PostgreSQL
service in CI, and the development database locally. Point it somewhere you are
willing to lose before running the suite.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete

from app.db.session import AsyncSessionLocal
from app.models.trade import Trade
from app.models.trade_state import TradeStateLog

#: Set once when the database turns out to be unreachable, so the rest of the
#: session does not repeat a connection attempt for every test.
_UNAVAILABLE = False


async def _empty_book() -> None:
    """Delete every trade, and its lifecycle rows first: that key has no cascade."""
    global _UNAVAILABLE
    if _UNAVAILABLE:
        return
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(TradeStateLog))
            await session.execute(delete(Trade))
            await session.commit()
    except Exception:
        # No database to reach, so there is nothing to wipe. Stop trying: a test
        # that needs one reports the connection problem itself, and a suite of pure
        # unit tests should not pay for a connection attempt it cannot make.
        _UNAVAILABLE = True


@pytest.fixture(autouse=True)
async def empty_book():
    """Start every test from an empty book, so a leftover cannot change a result."""
    await _empty_book()
    yield
