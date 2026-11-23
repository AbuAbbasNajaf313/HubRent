"""Web-Schicht mit Flask-Testclient, fester Uhr und In-Memory-Daten."""
from __future__ import annotations

import re
from datetime import timedelta

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.config import AppConfig
from app.domain.models import ReservationStatus as S
from app.repository.memory_repo import InMemoryRepository
from app.seed_data import DEMO_PASSWORD, build_seed, load_into_memory
from app.services.events import RecordingPublisher

from .conftest import berlin

NOW = berlin(2026, 11, 23, 12)  # Montag


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def fast_hash(pw: str) -> str:
    return generate_password_hash(pw, method="pbkdf2:sha256:1000")


@pytest.fixture
def ctx():
    repo = InMemoryRepository()
    seed = build_seed(password_hasher=fast_hash)
    load_into_memory(repo, seed)
    clock, pub = Clock(NOW), RecordingPublisher()
    app = create_app(AppConfig(secret_key="test"), repo=repo, publisher=pub, clock=clock)
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return app, repo, clock, pub, seed


@pytest.fixture
def client(ctx):
    return ctx[0].test_client()


def login(client, email, password=DEMO_PASSWORD):
    return client.post("/login", data={"email": email, "password": password})


def lena(ctx):
    return next(c for c in ctx[4].customers if c.full_name.startswith("Lena")).email


def type_and_hub(repo, type_name="Akku-Bohrhammer", hub_name="Hub Neukölln"):
    t = next(t for t in repo.list_device_types() if t.name == type_name)
    h = next(h for h in repo.list_hubs() if h.name == hub_name)
    return t.id, h.id


def book(client, repo, start="2026-11-30T10:00", rental_type="DAY", **extra):
    type_id, hub_id = type_and_hub(repo)
    data = {"device_type_id": type_id, "hub_id": hub_id, "rental_type": rental_type, "start": start, "days": "1", **extra}
    return client.post("/buchen", data=data)


# --- Öffentliche Seiten -------------------------------------------------------------

def test_landing_page(client):
    html = client.get("/").get_data(as_text=True)
    assert "24/7 aus dem Hub" in html and "Strike" in html


def test_catalog_lists_all_types_with_prices(client):
    html = client.get("/geraete").get_data(as_text=True)
    assert html.count("jetzt frei") + html.count("gerade belegt") == 8
    assert "16,00 €" in html and "165,00 €" in html  # 4 h Bohrhammer, Wochenende Parkett


def test_catalog_filter_by_category(client):
    html = client.get("/geraete?kategorie=Garten").get_data(as_text=True)
    assert "Vertikutierer" in html and "Stichsäge" not in html


def test_detail_page_and_unknown_type(client, ctx):
    type_id, _ = type_and_hub(ctx[1])
    html = client.get(f"/geraete/{type_id}").get_data(as_text=True)
    assert "Akku-Bohrhammer" in html and "Zum Reservieren anmelden" in html
    assert client.get("/geraete/gibt-es-nicht").status_code == 404


def test_availability_partial(client, ctx):
    type_id, hub_id = type_and_hub(ctx[1])
    q = f"/api/verfuegbarkeit?device_type_id={type_id}&hub_id={hub_id}&rental_type=DAY&start=2026-11-30T10:00&days=3"
    html = client.get(q).get_data(as_text=True)
    assert "60,00 €" in html and "2 Geräte frei" in html and "verbindlich" not in html

    soon = client.get(q.replace("2026-11-30", "2026-11-24")).get_data(as_text=True)
    assert 'name="binding"' in soon  # ≤ 48 h → Checkbox

    bad = client.get(q.replace("T10:00", "T10:30")).get_data(as_text=True)
    assert "vollen Stunde" in bad


# --- Registrierung & Login -----------------------------------------------------------

def test_register_logs_in(client, ctx):
    r = client.post(
        "/register",
        data={"full_name": "Kim", "email": "kim@example.com", "password": "geheim123", "password_repeat": "geheim123", "terms": "y"},
    )
    assert r.status_code == 302
    assert "Hallo Kim" in client.get("/konto").get_data(as_text=True)


def test_register_without_terms_fails(client):
    r = client.post(
        "/register",
        data={"full_name": "Kim", "email": "kim@example.com", "password": "geheim123", "password_repeat": "geheim123"},
    )
    assert r.status_code == 400 and "AGB" in r.get_data(as_text=True)


def test_login_wrong_password(client, ctx):
    r = login(client, lena(ctx), "falsch")
    assert r.status_code == 400 and "falsch" in r.get_data(as_text=True)


def test_account_requires_login(client):
    r = client.get("/konto")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_login_next_only_allows_local_paths(client, ctx):
    r = client.post("/login", data={"email": lena(ctx), "password": DEMO_PASSWORD, "next": "https://boese.example/"})
    assert r.headers["Location"] == "/konto"
    client.post("/logout")
    r = client.post("/login", data={"email": lena(ctx), "password": DEMO_PASSWORD, "next": "/geraete"})
    assert r.headers["Location"] == "/geraete"


def test_logout(client, ctx):
    login(client, lena(ctx))
    client.post("/logout")
    assert client.get("/konto").status_code == 302


# --- Buchen, Konto, Stornieren -------------------------------------------------------

def test_book_far_ahead_then_confirm_in_account(client, ctx):
    _, repo, _, pub, _ = ctx
    login(client, lena(ctx))
    r = book(client, repo)
    assert r.status_code == 302 and "neu=1" in r.headers["Location"]
    html = client.get(r.headers["Location"]).get_data(as_text=True)
    assert "Reserviert!" in html and "HR-" in html

    res = next(iter(repo.reservations.values()))
    assert res.status is S.PENDING and pub.types() == ["reservation.created"]

    client.post(f"/konto/reservierung/{res.id}/bestaetigen")
    assert repo.reservations[res.id].status is S.CONFIRMED
    html = client.get(f"/konto/reservierung/{res.id}").get_data(as_text=True)
    assert repo.reservations[res.id].pin in html


def test_short_notice_needs_binding_checkbox(client, ctx):
    repo = ctx[1]
    login(client, lena(ctx))
    r = book(client, repo, start="2026-11-24T10:00")
    assert not repo.reservations
    assert "verbindlich" in client.get(r.headers["Location"]).get_data(as_text=True)
    book(client, repo, start="2026-11-24T10:00", binding="y")
    assert next(iter(repo.reservations.values())).status is S.CONFIRMED


def test_booking_requires_login(client, ctx):
    r = book(client, ctx[1])
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    assert not ctx[1].reservations


def test_weekend_booking(client, ctx):
    repo = ctx[1]
    login(client, lena(ctx))
    book(client, repo, rental_type="WEEKEND", start="", weekend_start=berlin(2026, 11, 27, 14).isoformat())
    res = next(iter(repo.reservations.values()))
    assert res.price == 30 and res.end_at == berlin(2026, 11, 30, 10)


def test_cancel_free_in_account(client, ctx):
    repo = ctx[1]
    login(client, lena(ctx))
    book(client, repo)
    rid = next(iter(repo.reservations))
    r = client.post(f"/konto/reservierung/{rid}/stornieren", follow_redirects=True)
    assert repo.reservations[rid].status is S.CANCELLED_BY_CUSTOMER
    assert "Storniert" in r.get_data(as_text=True)


def test_other_customer_cannot_see_reservation(client, ctx):
    repo, seed = ctx[1], ctx[4]
    login(client, lena(ctx))
    book(client, repo)
    rid = next(iter(repo.reservations))
    client.post("/logout")
    login(client, seed.customers[2].email)
    assert client.get(f"/konto/reservierung/{rid}").status_code == 404
    client.post(f"/konto/reservierung/{rid}/stornieren")
    assert repo.reservations[rid].status is S.PENDING


def test_strike_card_in_account(client, ctx):
    jonas = ctx[4].customers[1]
    login(client, jonas.email)
    html = client.get("/konto").get_data(as_text=True)
    assert "3/5 saubere Mieten" in html and "50 %" in html


# --- Links aus der Mail --------------------------------------------------------------

def booked_token(client, ctx, start="2026-11-30T10:00"):
    login(client, lena(ctx))
    book(client, ctx[1], start=start)
    client.post("/logout")
    links = ctx[3].events[0][1]["links"]
    return re.search(r"/r/([^/]+)/", links["confirm"]).group(1)


def test_confirm_link_get_changes_nothing_post_confirms(client, ctx):
    token = booked_token(client, ctx)
    res = next(iter(ctx[1].reservations.values()))
    html = client.get(f"/r/{token}/bestaetigen").get_data(as_text=True)
    assert "verbindlich bestätigen" in html
    assert ctx[1].reservations[res.id].status is S.PENDING  # GET ändert nie etwas

    html = client.post(f"/r/{token}/bestaetigen").get_data(as_text=True)
    assert ctx[1].reservations[res.id].status is S.CONFIRMED
    assert ctx[1].reservations[res.id].pin in html


def test_cancel_link_shows_assessment_then_cancels(client, ctx):
    token = booked_token(client, ctx)
    html = client.get(f"/r/{token}/stornieren").get_data(as_text=True)
    assert "Kostenlos stornieren" in html
    client.post(f"/r/{token}/stornieren")
    assert next(iter(ctx[1].reservations.values())).status is S.CANCELLED_BY_CUSTOMER


def test_late_cancel_link_warns_about_strike(client, ctx):
    token = booked_token(client, ctx)
    client.post(f"/r/{token}/bestaetigen")
    ctx[2].t = berlin(2026, 11, 30, 2)  # < 24 h vor Start
    html = client.get(f"/r/{token}/stornieren").get_data(as_text=True)
    assert "Spätstorno" in html and "Verwarnung" in html


def test_invalid_and_expired_links(client, ctx):
    assert client.get("/r/quatsch/bestaetigen").status_code == 404
    token = booked_token(client, ctx)
    ctx[2].t = berlin(2026, 11, 30, 11)  # nach Mietbeginn → Token abgelaufen
    r = client.get(f"/r/{token}/stornieren")
    assert r.status_code == 404 and "abgelaufen" in r.get_data(as_text=True)


# --- Sicherheit ------------------------------------------------------------------------

def test_csrf_enabled_by_default(ctx):
    app = ctx[0]
    app.config["WTF_CSRF_ENABLED"] = True
    r = app.test_client().post("/login", data={"email": lena(ctx), "password": DEMO_PASSWORD})
    assert r.status_code == 302 and "/konto" not in r.headers["Location"]


def test_detail_preselects_hub_with_free_device(client, ctx):
    tempelhof = next(h.id for h in ctx[1].list_hubs() if h.name == "Hub Tempelhof")
    html = client.get("/geraete/type-PS").get_data(as_text=True)  # NK-PS-01 ist in Wartung
    assert f'<option selected value="{tempelhof}">' in html or f'value="{tempelhof}" selected' in html
