"""Hub-Terminal: Abholen per PIN, Rückgabe per Code, Sperre nach Fehlversuchen."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app import create_app
from app.config import AppConfig
from app.domain.models import RentalType, ReservationStatus as S
from app.repository.memory_repo import InMemoryRepository
from app.seed_data import build_seed, load_into_memory
from app.services.events import RecordingPublisher

from .conftest import berlin

NOW = berlin(2026, 11, 23, 12)
START = berlin(2026, 11, 24, 10)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def ctx():
    repo = InMemoryRepository()
    seed = build_seed(password_hasher=lambda p: "h")
    load_into_memory(repo, seed)
    clock, pub = Clock(NOW), RecordingPublisher()
    app = create_app(AppConfig(secret_key="t"), repo=repo, publisher=pub, clock=clock)
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    svc = app.extensions["hubrent"].rentals
    lena = repo.get_customer_by_email(seed.customers[0].email)
    res = svc.book(lena.id, "type-BH", "hub-NK", RentalType.FOUR_HOURS, START, NOW, binding_accepted=True).reservation
    return app.test_client(), repo, clock, pub, res


def test_terminal_pages(ctx):
    client = ctx[0]
    assert "Hub Neukölln" in client.get("/terminal").get_data(as_text=True)
    html = client.get("/terminal/hub-NK").get_data(as_text=True)
    assert "PIN aus deiner Bestätigungsmail" in html and "Fach öffnen" not in html
    assert "Reservierungscode" in client.get("/terminal/hub-NK?modus=rueckgabe").get_data(as_text=True)
    assert client.get("/terminal/gibtsnicht").status_code == 404


def test_pick_up_with_pin_opens_locker(ctx):
    client, repo, clock, pub, res = ctx
    clock.t = START - timedelta(minutes=10)
    r = client.post("/terminal/hub-NK/abholen", data={"pin": res.pin})
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "öffnet sich" in html and "locker-open" in html
    assert repo.reservations[res.id].status is S.PICKED_UP
    assert res.code in html  # Rückgabe-Code wird angezeigt
    assert "reservation.picked_up" in pub.types()


def test_pin_outside_window_or_wrong_hub_fails(ctx):
    client, repo, clock, _, res = ctx
    assert client.post("/terminal/hub-NK/abholen", data={"pin": res.pin}).status_code == 400  # zu früh
    clock.t = START
    assert client.post("/terminal/hub-TH/abholen", data={"pin": res.pin}).status_code == 400  # falscher Hub
    assert repo.reservations[res.id].status is S.CONFIRMED


def test_five_wrong_pins_lock_the_terminal(ctx):
    client, repo, clock, _, res = ctx
    clock.t = START
    for i in range(5):
        r = client.post("/terminal/hub-NK/abholen", data={"pin": "000000"})
        assert r.status_code == 400
    assert "kurz gesperrt" in r.get_data(as_text=True)
    locked = client.post("/terminal/hub-NK/abholen", data={"pin": res.pin})  # auch die richtige PIN
    assert locked.status_code == 429 and "Zu viele Fehlversuche" in locked.get_data(as_text=True)
    assert repo.reservations[res.id].status is S.CONFIRMED
    clock.t = START + timedelta(minutes=1, seconds=1)
    assert client.post("/terminal/hub-NK/abholen", data={"pin": res.pin}).status_code == 200


def test_return_by_code_without_prefix(ctx):
    client, repo, clock, pub, res = ctx
    clock.t = START
    client.post("/terminal/hub-NK/abholen", data={"pin": res.pin})
    clock.t = START + timedelta(hours=4)
    r = client.post("/terminal/hub-NK/rueckgabe", data={"code": res.code.removeprefix("HR-").lower()})
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Pünktlich zurückgegeben" in html
    assert repo.reservations[res.id].status is S.RETURNED
    assert "reservation.returned" in pub.types()


def test_return_at_wrong_hub(ctx):
    client, repo, clock, _, res = ctx
    clock.t = START
    client.post("/terminal/hub-NK/abholen", data={"pin": res.pin})
    r = client.post("/terminal/hub-TH/rueckgabe", data={"code": res.code})
    assert r.status_code == 400 and "Hub Neukölln" in r.get_data(as_text=True)
