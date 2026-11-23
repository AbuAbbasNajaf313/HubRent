"""Demo-Daten aus Abschnitt 6 der Spezifikation."""
from collections import Counter
from decimal import Decimal

from app.domain.models import DeviceStatus
from app.repository.memory_repo import InMemoryRepository
from app.seed_data import build_seed, demo_email, load_into_memory


def fast_hash(pw: str) -> str:  # echter Hash ist absichtlich langsam (scrypt)
    return "hash:" + pw


def seed(**kw):
    return build_seed(password_hasher=fast_hash, **kw)


def test_two_hubs():
    names = {h.name for h in seed().hubs}
    assert names == {"Hub Neukölln", "Hub Tempelhof"}


def test_eight_device_types_with_spec_prices():
    prices = {t.name: t.daily_rate for t in seed().device_types}
    assert prices == {
        "Akku-Bohrhammer": Decimal("20.00"),
        "Stichsäge": Decimal("15.00"),
        "Teppichreiniger": Decimal("30.00"),
        "Fliesenschneider": Decimal("25.00"),
        "Tapetenablöser": Decimal("25.00"),
        "Hochdruckreiniger": Decimal("35.00"),
        "Vertikutierer": Decimal("40.00"),
        "Parkettschleifmaschine": Decimal("110.00"),
    }


def test_categories_come_from_spec_list():
    allowed = {"Bohren", "Reinigen", "Schleifen", "Sägen", "Garten", "Renovieren"}
    assert {t.category for t in seed().device_types} <= allowed


def test_each_type_has_one_to_three_devices_on_both_hubs():
    s = seed()
    per_type = Counter(d.device_type_id for d in s.devices)
    assert set(per_type) == {t.id for t in s.device_types}
    assert all(1 <= n <= 3 for n in per_type.values())
    assert {d.hub_id for d in s.devices} == {h.id for h in s.hubs}


def test_exactly_one_device_in_maintenance():
    assert sum(d.status is DeviceStatus.MAINTENANCE for d in seed().devices) == 1


def test_device_codes_and_lockers_are_unique():
    devices = seed().devices
    assert len({d.code for d in devices}) == len(devices)
    assert len({(d.hub_id, d.locker_number) for d in devices}) == len(devices)


def test_three_demo_customers_with_strike_levels():
    customers = sorted(seed().customers, key=lambda c: c.strikes)
    assert [(c.strikes, c.clean_streak) for c in customers] == [(0, 0), (1, 3), (3, 0)]
    assert all(c.password_hash.startswith("hash:") for c in customers)
    assert all(c.terms_accepted_at is not None for c in customers)


def test_demo_email_uses_plus_addressing_when_base_given():
    assert demo_email("lena", None) == "lena@hubrent-demo.example"
    assert demo_email("lena", "Max.Muster@Gmail.com") == "max.muster+lena@gmail.com"


def test_seed_customers_use_email_base():
    emails = {c.email for c in seed(email_base="me@gmail.com").customers}
    assert all(e.startswith("me+") and e.endswith("@gmail.com") for e in emails)


def test_load_into_memory_makes_catalog_usable():
    repo = InMemoryRepository()
    s = seed()
    load_into_memory(repo, s)
    assert len(repo.list_hubs()) == 2
    assert len(repo.list_device_types()) == 8
    assert len(repo.list_devices()) == len(s.devices)
    assert repo.get_customer_by_email(s.customers[0].email) is not None
