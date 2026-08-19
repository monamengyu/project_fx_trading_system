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
