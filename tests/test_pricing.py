from datetime import timedelta, timezone
from decimal import Decimal

import pytest

from app.domain.errors import InvalidBookingTime
from app.domain.models import RentalType
from app.domain.pricing import compute_end, compute_price, validate_start

from .conftest import berlin


@pytest.mark.parametrize(
    "rental_type, rate, days, expected",
    [
        (RentalType.FOUR_HOURS, Decimal("20"), 1, Decimal("16.00")),
        (RentalType.FOUR_HOURS, Decimal("110"), 1, Decimal("88.00")),
        (RentalType.DAY, Decimal("20"), 1, Decimal("20.00")),
        (RentalType.DAY, Decimal("20"), 3, Decimal("60.00")),
        (RentalType.WEEKEND, Decimal("20"), 1, Decimal("30.00")),
        (RentalType.WEEKEND, Decimal("110"), 1, Decimal("165.00")),
        (RentalType.FOUR_HOURS, Decimal("15.99"), 1, Decimal("12.79")),
    ],
)
def test_prices(rental_type, rate, days, expected):
    assert compute_price(rental_type, rate, days) == expected


def test_four_hours_end(rules):
    start = berlin(2026, 12, 1, 9)
    assert compute_end(RentalType.FOUR_HOURS, start, rules) == berlin(2026, 12, 1, 13).astimezone(timezone.utc)


def test_day_end_multiple_days(rules):
    start = berlin(2026, 12, 1, 9)
    assert compute_end(RentalType.DAY, start, rules, days=3) == start + timedelta(days=3)


@pytest.mark.parametrize("days", [0, 15])
def test_day_out_of_range(rules, days):
    with pytest.raises(InvalidBookingTime):
        compute_end(RentalType.DAY, berlin(2026, 12, 1, 9), rules, days=days)


def test_weekend_window(rules):
    end = compute_end(RentalType.WEEKEND, berlin(2026, 12, 4, 14), rules)
    assert end == berlin(2026, 12, 7, 10).astimezone(timezone.utc)


def test_weekend_must_start_friday_14(rules):
    with pytest.raises(InvalidBookingTime):
        compute_end(RentalType.WEEKEND, berlin(2026, 12, 4, 15), rules)
    with pytest.raises(InvalidBookingTime):
        compute_end(RentalType.WEEKEND, berlin(2026, 12, 5, 14), rules)


def test_weekend_over_spring_dst_change(rules):
    # Zeitumstellung So 28.03.2027: Mo 10:00 ist dann CEST (UTC+2)
    end = compute_end(RentalType.WEEKEND, berlin(2027, 3, 26, 14), rules)
    assert end.hour == 8 and end.day == 29  # 10:00 CEST = 08:00 UTC
    assert end - berlin(2027, 3, 26, 14) == timedelta(hours=67)


def test_weekend_over_autumn_dst_change(rules):
    end = compute_end(RentalType.WEEKEND, berlin(2027, 10, 29, 14), rules)
    assert end.astimezone(berlin(2027, 1, 1).tzinfo).hour == 10
    assert end - berlin(2027, 10, 29, 14) == timedelta(hours=69)


def test_naive_datetime_rejected(rules):
    from datetime import datetime

    with pytest.raises(ValueError):
        compute_end(RentalType.DAY, datetime(2026, 12, 1, 9), rules)


def test_start_too_soon(rules, now):
    with pytest.raises(InvalidBookingTime):
        validate_start(now + timedelta(minutes=10), now, rules, RentalType.DAY)


def test_start_too_far(rules, now):
    with pytest.raises(InvalidBookingTime):
        validate_start(now + timedelta(days=61), now, rules, RentalType.DAY)


def test_start_must_be_full_hour(rules, now):
    with pytest.raises(InvalidBookingTime):
        validate_start(berlin(2026, 11, 25, 9, 30), now, rules, RentalType.DAY)
    validate_start(berlin(2026, 11, 25, 9), now, rules, RentalType.DAY)


def test_demo_mode_allows_minute_starts(now):
    from app.domain.rule_config import RuleConfig

    demo = RuleConfig.from_env({"DEMO_MODE": "true"})
    validate_start(now + timedelta(minutes=5), now, demo, RentalType.FOUR_HOURS)
