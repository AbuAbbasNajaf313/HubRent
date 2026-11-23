"""Interne API für n8n: Shared Secret, Idempotenz, Antwortformat."""
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

SECRET = "s3cret-fuer-tests"
NOW = berlin(2026, 11, 23, 12)
START_FAR = berlin(2026, 11, 30, 10)
START_SOON = berlin(2026, 11, 24, 10)
H = {"X-Internal-Secret": SECRET}


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
    clock = Clock(NOW)
    app = create_app(
        AppConfig(secret_key="t", internal_api_secret=SECRET, public_base_url="http://hubrent.test"),
        repo=repo,
        publisher=RecordingPublisher(),
        clock=clock,
    )
    app.config["TESTING"] = True  # CSRF bleibt an: die API muss trotzdem funktionieren
    svc = app.extensions["hubrent"].rentals
    jonas = repo.get_customer_by_email(seed.customers[1].email)  # 1 Strike
    return app.test_client(), repo, clock, svc, jonas


def book(svc, customer, start, now, type_id="type-PS", hub_id="hub-TH"):
    binding = start - now <= timedelta(hours=48)
    return svc.book(customer.id, type_id, hub_id, RentalType.DAY, start, now, binding_accepted=binding)


# --- Absicherung ------------------------------------------------------------------

@pytest.mark.parametrize("headers", [{}, {"X-Internal-Secret": "falsch"}, {"X-Internal-Secret": ""}])
def test_wrong_or_missing_secret_is_401(ctx, headers):
    client = ctx[0]
    assert client.get("/api/internal/health", headers=headers).status_code == 401
    assert client.post("/api/internal/reservations/x/no-show", headers=headers).status_code == 401


def test_api_disabled_without_configured_secret():
    app = create_app(AppConfig(secret_key="t", internal_api_secret=""), repo=InMemoryRepository(), publisher=RecordingPublisher())
    r = app.test_client().get("/api/internal/health", headers={"X-Internal-Secret": ""})
    assert r.status_code == 503


def test_health(ctx):
    r = ctx[0].get("/api/internal/health", headers=H)
    assert r.status_code == 200 and r.json["status"] == "ok"


def test_unknown_reservation_is_404_json(ctx):
    r = ctx[0].post("/api/internal/reservations/gibtsnicht/auto-cancel", headers=H)
    assert r.status_code == 404 and r.json["error"]


def test_get_not_allowed_for_actions(ctx):
    assert ctx[0].get("/api/internal/reservations/x/no-show", headers=H).status_code == 405


# --- Erinnerung -------------------------------------------------------------------

def test_reminder_sent_returns_fresh_links_once(ctx):
    client, repo, clock, svc, jonas = ctx
    booked = book(svc, jonas, START_FAR, NOW)
    rid = booked.reservation.id
    url = f"/api/internal/reservations/{rid}/reminder-sent"

    early = client.post(url, headers=H)
    assert early.status_code == 200 and early.json["changed"] is False and "links" not in early.json

    clock.t = START_FAR - timedelta(hours=47)
    r = client.post(url, headers=H)
    body = r.json
    assert body["changed"] is True
    assert body["links"]["confirm"].startswith("http://hubrent.test/r/")
    assert booked.token not in body["links"]["confirm"]  # neuer Token
    assert body["reservation"]["code"] == booked.reservation.code
    assert body["customer"]["email"] == jonas.email and body["hub"]["name"] == "Hub Tempelhof"
    assert repo.reservations[rid].reminder_sent_at is not None

    again = client.post(url, headers=H).json
    assert again["changed"] is False and "links" not in again  # idempotent, kein neuer Token


# --- Auto-Storno ------------------------------------------------------------------

def test_auto_cancel_only_after_deadline_and_idempotent(ctx):
    client, repo, clock, svc, jonas = ctx
    rid = book(svc, jonas, START_FAR, NOW).reservation.id
    url = f"/api/internal/reservations/{rid}/auto-cancel"
    assert client.post(url, headers=H).json["changed"] is False

    clock.t = START_FAR - timedelta(hours=24)
    body = client.post(url, headers=H).json
    assert body["changed"] is True and body["reservation"]["status"] == "CANCELLED_AUTO"
    assert body["fee"] == {"amount": "0.00", "currency": "EUR"}
    assert client.post(url, headers=H).json["changed"] is False
    assert repo.customers[jonas.id].strikes == 1  # kein Strike


# --- No-Show ----------------------------------------------------------------------

def test_no_show_gives_exactly_one_strike_and_fee(ctx):
    client, repo, clock, svc, jonas = ctx
    rid = book(svc, jonas, START_SOON, NOW).reservation.id
    url = f"/api/internal/reservations/{rid}/no-show"

    assert client.post(url, headers=H).json["changed"] is False  # zu früh

    clock.t = START_SOON + timedelta(hours=2, minutes=1)
    body = client.post(url, headers=H).json
    assert body["changed"] is True and body["reservation"]["status"] == "NO_SHOW"
    assert body["customer"]["strikes"] == 2 and body["customer"]["clean_streak"] == 0
    assert body["fee"] == {"amount": "55.00", "currency": "EUR"}  # 50 % von 110 €
    assert "0/5" in body["customer"]["strike_text"]

    second = client.post(url, headers=H).json
    assert second["changed"] is False and second["customer"]["strikes"] == 2
    assert repo.customers[jonas.id].strikes == 2 and len(repo.strike_events) == 1


def test_no_show_on_picked_up_is_noop(ctx):
    client, repo, clock, svc, jonas = ctx
    res = book(svc, jonas, START_SOON, NOW).reservation
    svc.pick_up("hub-TH", res.pin, START_SOON)
    clock.t = START_SOON + timedelta(hours=3)
    body = client.post(f"/api/internal/reservations/{res.id}/no-show", headers=H).json
    assert body["changed"] is False and body["reservation"]["status"] == S.PICKED_UP.value
