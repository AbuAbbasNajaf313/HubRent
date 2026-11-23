from decimal import Decimal

import pytest

from app.domain.models import ViolationType
from app.domain.strikes import calculate_fee, progress_text, register_return, register_violation


@pytest.mark.parametrize(
    "strikes_after, rate, fee",
    [
        (1, Decimal("20"), Decimal("0.00")),
        (2, Decimal("20"), Decimal("10.00")),
        (3, Decimal("20"), Decimal("15.00")),
        (4, Decimal("20"), Decimal("15.00")),
        (2, Decimal("110"), Decimal("55.00")),
        (3, Decimal("110"), Decimal("82.50")),
        (2, Decimal("15.99"), Decimal("8.00")),  # 7,995 → kaufmännisch 8,00
    ],
)
def test_fee_table(strikes_after, rate, fee):
    assert calculate_fee(strikes_after, rate) == fee


def test_first_violation_is_warning():
    r = register_violation(0, ViolationType.NO_SHOW, Decimal("20"))
    assert (r.strikes_after, r.clean_streak_after, r.fee) == (1, 0, Decimal("0.00"))


def test_violation_resets_streak_and_charges():
    r = register_violation(1, ViolationType.LATE_CANCEL, Decimal("110"))
    assert r.strikes_after == 2 and r.clean_streak_after == 0 and r.fee == Decimal("55.00")


def test_five_clean_rentals_reduce_one_strike():
    strikes, streak = 2, 0
    for i in range(4):
        res = register_return(strikes, streak, on_time=True)
        strikes, streak = res.strikes_after, res.clean_streak_after
        assert not res.strike_reduced
    res = register_return(strikes, streak, on_time=True)
    assert res.strike_reduced and res.strikes_after == 1 and res.clean_streak_after == 0


def test_late_return_resets_streak():
    res = register_return(2, 4, on_time=False)
    assert res.strikes_after == 2 and res.clean_streak_after == 0 and not res.strike_reduced


def test_no_banking_without_strikes():
    res = register_return(0, 0, on_time=True)
    assert res.strikes_after == 0 and res.clean_streak_after == 0


def test_progress_text():
    assert "3/5" in progress_text(1, 3)
    assert "Keine Strikes" in progress_text(0, 0)
