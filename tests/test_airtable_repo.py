"""AirtableRepository gegen eine Fake-API (kein Netzwerk, kein Token nötig)."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.domain.models import (
    Customer,
    Device,
    DeviceStatus,
    RentalType,
    Reservation,
    ReservationStatus as S,
    ViolationType,
)
from app.repository import airtable_schema as T
from app.repository.airtable_repo import AirtableRepository, make_retry
from app.repository.base import EventLogEntry, Fee, StrikeEvent
from app.seed_data import build_seed
from app.services.events import RecordingPublisher
from app.services.rentals import RentalService

from .conftest import berlin
from .fake_airtable import FakeBase

NOW = berlin(2026, 11, 23, 12)


@pytest.fixture
def base():
    return FakeBase()


@pytest.fixture
def repo(base):
    return AirtableRepository(base)


@pytest.fixture
def seeded(base, repo):
    """Stammdaten direkt in die Fake-Tabellen, wie es scripts/seed.py tut."""
    from app.repository.airtable_setup import seed_airtable

    ids = seed_airtable(base, build_seed(password_hasher=lambda p: "h"))
    return repo, ids


def make_res(device_id: str, customer_id: str, **kw) -> Reservation:
    start = kw.pop("start", berlin(2026, 11, 30, 10))
    defaults = dict(
        id="",
        code="HR-ABC123",
        customer_id=customer_id,
        device_id=device_id,
        rental_type=RentalType.DAY,
        start_at=start.astimezone(timezone.utc),
        end_at=(start + timedelta(days=1)).astimezone(timezone.utc),
        price=Decimal("20.00"),
        daily_rate_snapshot=Decimal("20.00"),
        status=S.PENDING,
        created_at=NOW.astimezone(timezone.utc),
    )
    defaults.update(kw)
    return Reservation(**defaults)


# --- Stammdaten -----------------------------------------------------------------

def test_master_data_roundtrip(seeded):
    repo, ids = seeded
    hubs = {h.name: h for h in repo.list_hubs()}
    assert hubs["Hub Neukölln"].address.startswith("Karl-Marx-Straße")
    assert hubs["Hub Neukölln"].active is True

    types = {t.name: t for t in repo.list_device_types()}
    assert types["Parkettschleifmaschine"].daily_rate == Decimal("110.00")
    assert isinstance(types["Stichsäge"].daily_rate, Decimal)

    pk = repo.get_device(ids["devices"]["NK-PS-01"])
    assert pk.status is DeviceStatus.MAINTENANCE
    assert pk.hub_id == ids["hubs"]["hub-NK"]
    assert pk.device_type_id == ids["device_types"]["type-PS"]


def test_list_devices_filters_by_type_and_hub(seeded):
    repo, ids = seeded
    bh = ids["device_types"]["type-BH"]
    nk = ids["hubs"]["hub-NK"]
    assert {d.code for d in repo.list_devices(bh, nk)} == {"NK-BH-01", "NK-BH-02"}
    assert len(repo.list_devices(device_type_id=bh)) == 3
    assert all(d.hub_id == nk for d in repo.list_devices(hub_id=nk))


def test_unknown_ids_return_none(repo):
    assert repo.get_hub("recDOESNOTEXIST01") is None
    assert repo.get_device("kein-airtable-id") is None
    assert repo.get_reservation("recDOESNOTEXIST02") is None


# --- Kunden ---------------------------------------------------------------------

def test_customer_add_find_update(repo):
    c = repo.add_customer(Customer("", "  Kim@Example.COM ", "Kim", password_hash="x"))
    assert c.id.startswith("rec") and c.email == "kim@example.com"
    found = repo.get_customer_by_email("KIM@example.com")
    assert found.id == c.id and found.strikes == 0 and found.clean_streak == 0
    found.strikes, found.clean_streak = 2, 1
    repo.update_customer(found)
    again = repo.get_customer(c.id)
    assert (again.strikes, again.clean_streak) == (2, 1)


def test_email_with_quote_is_escaped(repo):
    repo.add_customer(Customer("", "o'neil@example.com", "O'Neil"))
    assert repo.get_customer_by_email("o'neil@example.com").full_name == "O'Neil"


# --- Reservierungen -------------------------------------------------------------

def test_reservation_roundtrip_keeps_types(seeded):
    repo, ids = seeded
    dev = ids["devices"]["NK-BH-01"]
    cus = repo.add_customer(Customer("", "a@example.com", "A")).id
    r = repo.add_reservation(make_res(dev, cus, token_hash="abc", token_expires_at=NOW))
    got = repo.get_reservation(r.id)
    assert got.code == "HR-ABC123"
    assert got.status is S.PENDING and got.rental_type is RentalType.DAY
    assert got.price == Decimal("20.00") and isinstance(got.price, Decimal)
    assert got.start_at == r.start_at and got.start_at.tzinfo is not None
    assert got.token_expires_at == NOW
    assert got.pin == "" and got.confirmed_at is None


def test_update_reservation_sets_and_clears_fields(seeded):
    repo, ids = seeded
    dev = ids["devices"]["NK-BH-01"]
    cus = repo.add_customer(Customer("", "a@example.com", "A")).id
    r = repo.add_reservation(make_res(dev, cus))
    r.status, r.pin, r.confirmed_at = S.CONFIRMED, "123456", NOW
    repo.update_reservation(r)
    assert repo.get_reservation(r.id).pin == "123456"
    r.pin, r.confirmed_at = "", None
    repo.update_reservation(r)
    got = repo.get_reservation(r.id)
    assert got.pin == "" and got.confirmed_at is None and got.status is S.CONFIRMED


def test_reservation_lookups(seeded):
    repo, ids = seeded
    d1, d2 = ids["devices"]["NK-BH-01"], ids["devices"]["NK-BH-02"]
    cus = repo.add_customer(Customer("", "a@example.com", "A")).id
    other = repo.add_customer(Customer("", "b@example.com", "B")).id
    r1 = repo.add_reservation(make_res(d1, cus, code="HR-AAAAAA", token_hash="h1"))
    r2 = repo.add_reservation(make_res(d2, cus, code="HR-BBBBBB", start=berlin(2026, 12, 5, 10)))
    repo.add_reservation(make_res(d2, other, code="HR-CCCCCC"))

    assert {r.id for r in repo.list_reservations_for_devices([d1])} == {r1.id}
    assert len(repo.list_reservations_for_devices([d1, d2])) == 3
    assert repo.list_reservations_for_devices([]) == []
    assert [r.id for r in repo.list_reservations_for_customer(cus)] == [r2.id, r1.id]  # neueste zuerst
    assert repo.find_reservation_by_token_hash("h1").id == r1.id
    assert repo.find_reservation_by_token_hash("nope") is None
    assert repo.find_reservation_by_code("hr-bbbbbb").id == r2.id


def test_many_devices_are_queried_in_chunks(seeded, base):
    repo, _ = seeded
    repo.list_reservations_for_devices([f"rec{i:014d}" for i in range(75)])
    formulas = base(T.RESERVATIONS).formulas
    assert len(formulas) == 3  # 30 + 30 + 15


# --- Strikes, Gebühren, Protokoll ----------------------------------------------

def test_strikes_fees_and_event_log(seeded, base):
    repo, ids = seeded
    cus = repo.add_customer(Customer("", "a@example.com", "A")).id
    r = repo.add_reservation(make_res(ids["devices"]["NK-BH-01"], cus))
    repo.add_strike_event(StrikeEvent(cus, r.id, "NO_SHOW", 2, Decimal("10.00"), NOW))
    repo.add_fee(Fee(cus, r.id, Decimal("10.00"), ViolationType.NO_SHOW))
    repo.add_event_log(EventLogEntry("reservation.no_show", "n8n", r.id, {"fee": "10.00"}))

    fees = repo.list_fees_for_customer(cus)
    assert len(fees) == 1 and fees[0].amount == Decimal("10.00")
    assert fees[0].reason is ViolationType.NO_SHOW and fees[0].status == "OPEN"

    strike = next(iter(base(T.STRIKE_EVENTS).records.values()))
    assert strike["customer"] == [cus] and strike["type"] == "NO_SHOW"
    log = next(iter(base(T.EVENT_LOG).records.values()))
    assert log["payload"] == '{"fee": "10.00"}' and log["source"] == "n8n"


# --- Zusammenspiel mit dem Service ---------------------------------------------

def test_service_flow_on_airtable_repo(seeded, rules):
    repo, ids = seeded
    svc = RentalService(repo, rules, RecordingPublisher())
    cus = repo.get_customer_by_email(build_seed(password_hasher=str).customers[1].email)
    bh, nk = ids["device_types"]["type-BH"], ids["hubs"]["hub-NK"]

    booked = svc.book(cus.id, bh, nk, RentalType.DAY, berlin(2026, 11, 30, 10), NOW)
    confirmed = svc.confirm(booked.token, NOW + timedelta(hours=1))
    assert confirmed.reservation.status is S.CONFIRMED
    assert repo.get_reservation(booked.reservation.id).pin == confirmed.reservation.pin

    # zweites Gerät ist noch frei, drittes Buchen scheitert
    svc.book(cus.id, bh, nk, RentalType.DAY, berlin(2026, 11, 30, 10), NOW)
    from app.domain.errors import NotAvailable

    with pytest.raises(NotAvailable):
        svc.book(cus.id, bh, nk, RentalType.DAY, berlin(2026, 11, 30, 10), NOW)


# --- Retry ----------------------------------------------------------------------

def test_retry_only_repeats_rejected_requests():
    retry = make_retry()
    assert 429 in retry.status_forcelist
    assert retry.allowed_methods is None  # auch POST/PATCH: 429 heißt "nicht ausgeführt"
    assert retry.read == 0  # Timeout nach dem Senden: nicht wiederholen (sonst evtl. doppelt angelegt)
    assert retry.respect_retry_after_header


def test_service_flow_with_cache_needs_fewer_calls(base, rules):
    from app.repository.airtable_setup import seed_airtable
    from app.repository.cached_repo import CachedRepository

    ids = seed_airtable(base, build_seed(password_hasher=lambda p: "h"))
    repo = CachedRepository(AirtableRepository(base))
    svc = RentalService(repo, rules, RecordingPublisher())
    for _ in range(3):
        svc.catalog(NOW)
    devices_table = base(T.DEVICES)
    reads_before = len(devices_table.formulas)
    cus = repo.get_customer_by_email(build_seed(password_hasher=str).customers[0].email)
    booked = svc.book(cus.id, ids["device_types"]["type-BH"], ids["hubs"]["hub-NK"], RentalType.DAY, berlin(2026, 11, 30, 10), NOW)
    assert booked.reservation.code.startswith("HR-")
    assert len(devices_table.formulas) == reads_before  # Geräte kamen aus dem Cache
