"""End-to-End-Abläufe der Service-Schicht mit InMemoryRepository."""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.domain.errors import DomainError, InvalidBookingTime, NotAvailable
from app.domain.models import (
    Customer,
    DeviceStatus,
    DeviceType,
    Hub,
    RentalType,
    ReservationStatus as S,
)
from app.repository.memory_repo import InMemoryRepository
from app.services.events import RecordingPublisher
from app.services.rentals import RentalService

from .conftest import berlin, make_device

NOW = berlin(2026, 11, 23, 12)
START_FAR = berlin(2026, 11, 30, 10)   # > 48 h → PENDING
START_SOON = berlin(2026, 11, 24, 10)  # ≤ 48 h → CONFIRMED


@pytest.fixture
def env(rules):
    repo = InMemoryRepository()
    repo.hubs["h1"] = Hub("h1", "Hub Neukölln", "Karl-Marx-Str. 1, Berlin")
    repo.device_types["t1"] = DeviceType("t1", "Akku-Bohrhammer", "Bohren", Decimal("20.00"))
    repo.device_types["t2"] = DeviceType("t2", "Parkettschleifmaschine", "Schleifen", Decimal("110.00"))
    repo.devices["d1"] = make_device("d1", "t1", "h1", locker=1)
    repo.devices["d2"] = make_device("d2", "t2", "h1", locker=2)
    repo.customers["c1"] = Customer("c1", "kunde@example.com", "Test Kunde")
    pub = RecordingPublisher()
    return RentalService(repo, rules, pub), repo, pub


def test_booking_far_ahead_is_pending_without_pin(env):
    svc, repo, pub = env
    res = svc.book("c1", "t1", "h1", RentalType.DAY, START_FAR, NOW)
    assert res.reservation.status is S.PENDING and res.reservation.pin == ""
    assert res.reservation.price == Decimal("20.00")
    assert pub.types() == ["reservation.created"]
    assert "links" in pub.events[0][1]


def test_short_notice_requires_binding_checkbox(env):
    svc, *_ = env
    with pytest.raises(InvalidBookingTime):
        svc.book("c1", "t1", "h1", RentalType.DAY, START_SOON, NOW)


def test_short_notice_booking_confirmed_with_pin(env):
    svc, _, pub = env
    res = svc.book("c1", "t1", "h1", RentalType.FOUR_HOURS, START_SOON, NOW, binding_accepted=True)
    assert res.reservation.status is S.CONFIRMED and len(res.reservation.pin) == 6
    assert res.reservation.price == Decimal("16.00")
    assert pub.types() == ["reservation.confirmed"]


def test_double_booking_prevented(env):
    svc, *_ = env
    svc.book("c1", "t1", "h1", RentalType.DAY, START_FAR, NOW)
    with pytest.raises(NotAvailable):
        svc.book("c1", "t1", "h1", RentalType.FOUR_HOURS, START_FAR + timedelta(hours=2), NOW)


def test_maintenance_device_not_bookable(env):
    svc, repo, _ = env
    repo.devices["d1"].status = DeviceStatus.MAINTENANCE
    with pytest.raises(NotAvailable):
        svc.book("c1", "t1", "h1", RentalType.DAY, START_FAR, NOW)


def test_full_happy_path(env, rules):
    svc, repo, pub = env
    res = svc.book("c1", "t1", "h1", RentalType.DAY, START_FAR, NOW)
    rid = res.reservation.id

    # n8n: zu früh → nichts
    assert not svc.send_reminder(rid, NOW).changed
    # n8n: T-48h → Erinnerung mit neuem Token
    t48 = START_FAR - timedelta(hours=48)
    reminder = svc.send_reminder(rid, t48)
    assert reminder.changed and reminder.token != res.token
    assert not svc.send_reminder(rid, t48 + timedelta(minutes=5)).changed  # idempotent

    # alter Token funktioniert nicht mehr, neuer schon
    with pytest.raises(DomainError):
        svc.confirm(res.token, t48 + timedelta(hours=1))
    confirmed = svc.confirm(reminder.token, t48 + timedelta(hours=1))
    assert confirmed.reservation.status is S.CONFIRMED and confirmed.reservation.pin
    assert not svc.confirm(reminder.token, t48 + timedelta(hours=2)).changed  # doppelter Klick

    # Abholung am Terminal
    pin = confirmed.reservation.pin
    with pytest.raises(DomainError):
        svc.pick_up("h1", pin, START_FAR - timedelta(hours=1))  # zu früh
    picked = svc.pick_up("h1", pin, START_FAR + timedelta(minutes=10))
    assert picked.reservation.status is S.PICKED_UP and picked.extra["locker_number"] == 1

    # pünktliche Rückgabe
    returned = svc.return_item(rid, START_FAR + timedelta(hours=23))
    assert returned.reservation.status is S.RETURNED and returned.extra["on_time"]
    assert "reservation.returned" in pub.types()


def test_unconfirmed_auto_cancelled_free(env):
    svc, repo, _ = env
    rid = svc.book("c1", "t1", "h1", RentalType.DAY, START_FAR, NOW).reservation.id
    assert not svc.auto_cancel(rid, START_FAR - timedelta(hours=25)).changed
    res = svc.auto_cancel(rid, START_FAR - timedelta(hours=24))
    assert res.changed and res.reservation.status is S.CANCELLED_AUTO
    assert not svc.auto_cancel(rid, START_FAR - timedelta(hours=23)).changed
    assert repo.customers["c1"].strikes == 0
    # Gerät wieder frei
    svc.book("c1", "t1", "h1", RentalType.DAY, START_FAR, START_FAR - timedelta(hours=23), binding_accepted=True)


def test_no_show_strike_escalation(env):
    svc, repo, _ = env
    fees = []
    start = START_SOON
    for i in range(3):
        booked_at = start - timedelta(hours=5)
        rid = svc.book("c1", "t2", "h1", RentalType.DAY, start, booked_at, binding_accepted=True).reservation.id
        res = svc.mark_no_show(rid, start + timedelta(hours=3))
        assert res.changed and res.reservation.status is S.NO_SHOW
        assert not svc.mark_no_show(rid, start + timedelta(hours=4)).changed  # nur ein Strike
        fees.append(res.fee)
        start += timedelta(days=2)
    assert fees == [Decimal("0.00"), Decimal("55.00"), Decimal("82.50")]
    assert repo.customers["c1"].strikes == 3
    assert len(repo.fees) == 2 and len(repo.strike_events) == 3


def test_late_cancel_gives_strike_early_cancel_free(env):
    svc, repo, _ = env
    early = svc.book("c1", "t1", "h1", RentalType.DAY, START_FAR, NOW)
    t48 = START_FAR - timedelta(hours=48)
    token = svc.send_reminder(early.reservation.id, t48).token
    svc.confirm(token, t48)
    res = svc.cancel(token, START_FAR - timedelta(hours=2))
    assert res.reservation.status is S.CANCELLED_BY_CUSTOMER and not res.message.startswith("Kostenlos")
    assert repo.customers["c1"].strikes == 1 and res.fee == Decimal("0.00")


def test_cancel_by_other_customer_forbidden(env):
    svc, repo, _ = env
    repo.customers["c2"] = Customer("c2", "x@example.com", "Andere Person")
    rid = svc.book("c1", "t1", "h1", RentalType.DAY, START_FAR, NOW).reservation.id
    with pytest.raises(DomainError):
        svc.cancel_by_customer(rid, "c2", NOW)


def test_clean_returns_reduce_strike(env):
    svc, repo, pub = env
    repo.customers["c1"].strikes = 1
    repo.customers["c1"].clean_streak = 4
    rid = svc.book("c1", "t1", "h1", RentalType.FOUR_HOURS, START_SOON, NOW, binding_accepted=True).reservation
    svc.pick_up("h1", rid.pin, START_SOON)
    res = svc.return_item(rid.id, START_SOON + timedelta(hours=4))
    assert res.extra["strike_reduced"]
    assert repo.customers["c1"].strikes == 0
    assert "strike.reduced" in pub.types()


def test_quote(env):
    svc, *_ = env
    q = svc.quote("t2", "h1", RentalType.WEEKEND, berlin(2026, 12, 4, 14), NOW)
    assert q.price == Decimal("165.00") and q.free_devices == 1 and not q.binding
