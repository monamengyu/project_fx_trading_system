from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, timedelta


def is_business_day(d: date) -> bool:
    """Return True if ``d`` is a weekday (Mon-Fri)."""
    return d.weekday() < 5


def effective_trade_date(d: date) -> date:
    """Roll non-business days (weekends) forward to the next business day."""
    current = d
    while not is_business_day(current):
        current += timedelta(days=1)
    return current


def add_business_days(start: date, days: int) -> date:
    """Return the date ``days`` business days after ``start`` (Mon-Fri, weekends excluded)."""
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Monday-Friday
            added += 1
    return current


def spot_value_date(trade_date: date) -> date:
    """Standard spot value date: trade date + 2 business days."""
    return add_business_days(trade_date, 2)


# Ambient rather than a parameter because every caller that needs the trade date
# has to agree on it, including the schema validators reached when a TradeCreate
# is constructed. Those have no channel for receiving a date, so the alternative
# would be for the parser and the validators to disagree on which day it is.
_pinned_trade_date: ContextVar[date | None] = ContextVar("pinned_trade_date", default=None)


def current_trade_date() -> date:
    """Return the trade date a booking is anchored on.

    Today rolled forward to a business day, unless an evaluation run has pinned
    one with :func:`override_trade_date`.
    """
    pinned = _pinned_trade_date.get()
    return pinned if pinned is not None else effective_trade_date(date.today())


@contextmanager
def override_trade_date(value: date):
    """Pin :func:`current_trade_date` to ``value`` for the duration of the block.

    Lets a recorded evaluation corpus be replayed unchanged on a later day.
    Outside such a block the pinned value is ``None`` and this module behaves
    exactly as it did before.
    """
    token = _pinned_trade_date.set(effective_trade_date(value))
    try:
        yield
    finally:
        _pinned_trade_date.reset(token)
