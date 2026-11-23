from datetime import timedelta

import pytest

from app.domain.errors import InvalidTransition
from app.domain.models import ReservationStatus as S
from app.domain.rules import (
    FINAL_STATUSES,
    assess_cancellation,
    auto_cancel_due,
    can_confirm,
    can_pick_up,
    initial_status,
    is_on_time_return,
    no_show_due,
    reminder_due,
    transition,
)

from .conftest import berlin, make_reservation

START = berlin(2026, 12, 10, 10)


# --- Statusmaschine -----------------------------------------------------------

@pytest.mark.parametrize(
    "current, target",
    [
        (S.PENDING, S.CONFIRMED),
        (S.PENDING, S.CANCELLED_BY_CUSTOMER),
        (S.PENDING, S.CANCELLED_AUTO),
        (S.CONFIRMED, S.PICKED_UP),
        (S.CONFIRMED, S.CANCELLED_BY_CUSTOMER),
        (S.CONFIRMED, S.NO_SHOW),
        (S.PICKED_UP, S.RETURNED),
    ],
)
def test_allowed_transitions(current, target):
    r = make_reservation(start=START, status=current)
    transition(r, target)
    assert r.status is target


@pytest.mark.parametrize(
    "current, target",
    [
        (S.PENDING, S.PICKED_UP),
        (S.PENDING, S.NO_SHOW),
        (S.CONFIRMED, S.CANCELLED_AUTO),
        (S.PICKED_UP, S.NO_SHOW),
        (S.NO_SHOW, S.CONFIRMED),
        (S.RETURNED, S.PICKED_UP),
        (S.CANCELLED_AUTO, S.CONFIRMED),
    ],
)
def test_forbidden_transitions(current, target):
    r = make_reservation(start=START, status=current)
    with pytest.raises(InvalidTransition):
        transition(r, target)
    assert r.status is current


def test_final_statuses():
    assert FINAL_STATUSES == {S.RETURNED, S.CANCELLED_BY_CUSTOMER, S.CANCELLED_AUTO, S.NO_SHOW}


# --- Buchung ------------------------------------------------------------------

def test_booking_far_ahead_is_pending(rules):
    assert initial_status(START, START - timedelta(hours=49), rules) is S.PENDING


def test_short_notice_booking_is_binding(rules):
    assert initial_status(START, START - timedelta(hours=48), rules) is S.CONFIRMED
    assert initial_status(START, START - timedelta(hours=2), rules) is S.CONFIRMED


# --- Fristen ------------------------------------------------------------------

def test_reminder_due_window(rules):
    r = make_reservation(start=START)
    assert not reminder_due(r, START - timedelta(hours=49), rules)
    assert reminder_due(r, START - timedelta(hours=48), rules)
    assert reminder_due(r, START - timedelta(hours=30), rules)
    assert not reminder_due(r, START - timedelta(hours=24), rules)


def test_reminder_only_once(rules):
    r = make_reservation(start=START)
    r.reminder_sent_at = START - timedelta(hours=48)
    assert not reminder_due(r, START - timedelta(hours=47), rules)


def test_confirm_until_deadline(rules):
    r = make_reservation(start=START)
    assert can_confirm(r, START - timedelta(hours=24, seconds=1), rules)
    assert not can_confirm(r, START - timedelta(hours=24), rules)


def test_auto_cancel_due(rules):
    r = make_reservation(start=START)
    assert not auto_cancel_due(r, START - timedelta(hours=25), rules)
    assert auto_cancel_due(r, START - timedelta(hours=24), rules)
    r.status = S.CONFIRMED
    assert not auto_cancel_due(r, START - timedelta(hours=1), rules)


def test_pickup_window(rules):
    r = make_reservation(start=START, status=S.CONFIRMED)
    assert not can_pick_up(r, START - timedelta(minutes=31), rules)
    assert can_pick_up(r, START - timedelta(minutes=30), rules)
    assert can_pick_up(r, START + timedelta(hours=2), rules)
    assert not can_pick_up(r, START + timedelta(hours=2, seconds=1), rules)


def test_no_show_due(rules):
    r = make_reservation(start=START, status=S.CONFIRMED)
    assert not no_show_due(r, START + timedelta(hours=2), rules)
    assert no_show_due(r, START + timedelta(hours=2, seconds=1), rules)
    r.status = S.PICKED_UP
    assert not no_show_due(r, START + timedelta(hours=5), rules)


def test_on_time_return(rules):
    r = make_reservation(start=START, hours=24)
    assert is_on_time_return(r, r.end_at + timedelta(minutes=15), rules)
    assert not is_on_time_return(r, r.end_at + timedelta(minutes=16), rules)


# --- Stornierung ----------------------------------------------------------------

def test_cancel_pending_always_free(rules):
    r = make_reservation(start=START, status=S.PENDING)
    a = assess_cancellation(r, START - timedelta(hours=25), rules)
    assert a.allowed and a.free_of_charge


def test_cancel_confirmed_early_is_free(rules):
    r = make_reservation(start=START, status=S.CONFIRMED)
    a = assess_cancellation(r, START - timedelta(hours=24, seconds=1), rules)
    assert a.allowed and a.free_of_charge


def test_cancel_confirmed_late_is_strike(rules):
    r = make_reservation(start=START, status=S.CONFIRMED)
    a = assess_cancellation(r, START - timedelta(hours=23), rules)
    assert a.allowed and not a.free_of_charge


def test_cancel_grace_after_short_notice_booking(rules):
    booked = START - timedelta(hours=3)
    r = make_reservation(start=START, status=S.CONFIRMED, created_at=booked)
    assert assess_cancellation(r, booked + timedelta(minutes=15), rules).free_of_charge
    assert not assess_cancellation(r, booked + timedelta(minutes=16), rules).free_of_charge


@pytest.mark.parametrize("status", [S.PICKED_UP, S.RETURNED, S.NO_SHOW, S.CANCELLED_AUTO])
def test_cancel_not_allowed(rules, status):
    r = make_reservation(start=START, status=status)
    assert not assess_cancellation(r, START - timedelta(days=3), rules).allowed
