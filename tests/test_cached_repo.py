"""CachedRepository: weniger Airtable-Aufrufe, ohne veraltete Daten nach eigenen Änderungen."""
from __future__ import annotations

from collections import Counter

import pytest

from app.domain.models import Customer
from app.repository.cached_repo import CachedRepository
from app.repository.memory_repo import InMemoryRepository
from app.seed_data import build_seed, load_into_memory


class CountingRepo(InMemoryRepository):
    """Zählt Aufrufe wie Airtable-Requests."""

    def __init__(self):
        super().__init__()
        self.calls: Counter[str] = Counter()

    def __getattribute__(self, name):
        attr = super().__getattribute__(name)
        if not callable(attr) or name.startswith("_") or name == "calls":
            return attr
        calls = super().__getattribute__("calls")

        def counted(*args, **kwargs):  # erst beim Aufruf zählen, nicht beim Zugriff
            calls[name] += 1
            return attr(*args, **kwargs)

        return counted


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def setup():
    inner = CountingRepo()
    load_into_memory(inner, build_seed(password_hasher=lambda p: "h"))
    inner.calls.clear()
    clock = FakeClock()
    return CachedRepository(inner, ttl_seconds=300, customer_ttl_seconds=60, clock=clock), inner, clock


def test_master_data_is_loaded_once_per_ttl(setup):
    repo, inner, clock = setup
    for _ in range(5):
        repo.list_hubs()
        repo.get_hub("hub-NK")
        repo.list_device_types()
        repo.get_device_type("type-BH")
        repo.list_devices()
        repo.list_devices("type-BH", "hub-NK")
        repo.get_device("NK-BH-01")
    assert inner.calls["list_hubs"] == 1
    assert inner.calls["list_device_types"] == 1
    assert inner.calls["list_devices"] == 1
    assert inner.calls["get_hub"] == inner.calls["get_device"] == inner.calls["get_device_type"] == 0

    clock.t = 301
    repo.list_hubs()
    assert inner.calls["list_hubs"] == 2


def test_filters_and_unknown_ids_match_inner_repo(setup):
    repo, inner, _ = setup
    assert {d.code for d in repo.list_devices("type-BH", "hub-NK")} == {"NK-BH-01", "NK-BH-02"}
    assert {d.code for d in repo.list_devices(hub_id="hub-TH")} == {d.code for d in inner.list_devices(hub_id="hub-TH")}
    assert repo.get_hub("gibts-nicht") is None and repo.get_device("x") is None


def test_returned_objects_are_copies(setup):
    repo, *_ = setup
    repo.list_hubs()[0].name = "kaputt"
    assert all(h.name != "kaputt" for h in repo.list_hubs())


def test_customer_cached_and_invalidated_on_own_update(setup):
    repo, inner, clock = setup
    c = repo.get_customer_by_email("lena@hubrent-demo.example")
    for _ in range(3):
        repo.get_customer(c.id)
    assert inner.calls["get_customer"] == 0  # Login hat den Cache schon gefüllt

    c.strikes = 2
    repo.update_customer(c)
    assert repo.get_customer(c.id).strikes == 2  # sofort aktuell, nicht aus dem alten Cache

    assert inner.calls["get_customer"] == 0  # Write-through, kein erneutes Laden
    clock.t = 61
    repo.get_customer(c.id)
    assert inner.calls["get_customer"] == 1  # nach Ablauf der TTL frisch geladen


def test_reservations_are_never_cached(setup):
    repo, inner, _ = setup
    repo.list_reservations_for_devices(["NK-BH-01"])
    repo.list_reservations_for_devices(["NK-BH-01"])
    assert inner.calls["list_reservations_for_devices"] == 2


def test_new_customer_is_readable(setup):
    repo, *_ = setup
    added = repo.add_customer(Customer("", "neu@example.com", "Neu"))
    assert repo.get_customer(added.id).email == "neu@example.com"
