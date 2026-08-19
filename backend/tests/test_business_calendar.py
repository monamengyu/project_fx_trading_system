from datetime import date

from app.services.business_calendar import (
    add_business_days,
    effective_trade_date,
    is_business_day,
    spot_value_date,
)


def test_is_business_day():
    assert is_business_day(date(2026, 8, 17))  # Monday
    assert not is_business_day(date(2026, 8, 22))  # Saturday
    assert not is_business_day(date(2026, 8, 23))  # Sunday


def test_effective_trade_date_weekday_stays():
    assert effective_trade_date(date(2026, 8, 17)) == date(2026, 8, 17)


def test_effective_trade_date_saturday_rolls_to_monday():
    assert effective_trade_date(date(2026, 8, 22)) == date(2026, 8, 24)


def test_effective_trade_date_sunday_rolls_to_monday():
    assert effective_trade_date(date(2026, 8, 23)) == date(2026, 8, 24)


def test_add_business_days_skips_weekends():
    fri = date(2026, 8, 21)
    assert add_business_days(fri, 2) == date(2026, 8, 25)  # Fri -> Mon -> Tue
    assert spot_value_date(fri) == date(2026, 8, 25)
