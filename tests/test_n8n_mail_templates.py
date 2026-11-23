"""Die n8n-Mail-Vorlagen (JavaScript) laufen hier mit Node gegen echte Flask-Payloads.

So fällt auf, wenn Flask ein Feld umbenennt, das die Mail-Vorlage braucht.
Ohne installiertes Node wird der Test übersprungen.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

from app.domain.models import RentalType
from app.repository.memory_repo import InMemoryRepository
from app.seed_data import build_seed, load_into_memory
from app.services.events import RecordingPublisher
from app.services.rentals import RentalService

from .conftest import berlin

JS = Path(__file__).parent.parent / "n8n" / "src" / "mail_templates.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js nicht installiert")

HARNESS = """
const items = JSON.parse(require('fs').readFileSync(0, 'utf8')).map(j => ({ json: j }));
const $input = { all: () => items };
const run = new Function('$input', CODE);
process.stdout.write(JSON.stringify(run($input)));
"""


def render(bodies: list[dict]) -> list[dict]:
    script = "const CODE = " + json.dumps(JS.read_text(encoding="utf-8")) + ";\n" + HARNESS
    proc = subprocess.run(
        [NODE, "-e", script], input=json.dumps(bodies), capture_output=True, text=True, timeout=20, check=False
    )
    assert proc.returncode == 0, proc.stderr
    return [i["json"] for i in json.loads(proc.stdout)]


def webhook(event: str, payload: dict) -> dict:
    """So kommt ein Flask-Event im n8n-Webhook an: Daten unter "body"."""
    return {"headers": {}, "body": {"event": event, **payload}}


@pytest.fixture
def flow(rules):
    repo = InMemoryRepository()
    seed = build_seed(password_hasher=lambda p: "h")
    load_into_memory(repo, seed)
    pub = RecordingPublisher()
    svc = RentalService(repo, rules, pub, "http://hubrent.test")
    jonas = repo.get_customer_by_email(seed.customers[1].email)
    return svc, pub, jonas


NOW = berlin(2026, 11, 23, 12)


def test_all_flask_events_render(flow):
    svc, pub, jonas = flow
    far = svc.book(jonas.id, "type-BH", "hub-NK", RentalType.DAY, berlin(2026, 11, 30, 10), NOW)
    svc.confirm(far.token, NOW)
    soon = svc.book(jonas.id, "type-PS", "hub-TH", RentalType.DAY, berlin(2026, 11, 24, 10), NOW, binding_accepted=True)
    svc.cancel_by_customer(soon.reservation.id, jonas.id, NOW + timedelta(hours=1))  # Spätstorno → Strike 2
    out = render([webhook(t, p) for t, p in pub.events])
    by_event = {o["event"]: o for o in out}

    created = by_event["reservation.created"]
    assert created["send"] and created["to"] == jonas.email
    assert far.reservation.code in created["subject"] and "http://hubrent.test/r/" in created["html"]

    confirmed = next(o for o in out if o["event"] == "reservation.confirmed" and o["reservation_id"] == far.reservation.id)
    pin = svc.repo.get_reservation(far.reservation.id).pin
    assert pin in confirmed["subject"] and pin in confirmed["html"] and pin in confirmed["text"]

    cancelled = by_event["reservation.cancelled"]
    assert "Strike" in cancelled["text"] and "55,00 €" in cancelled["text"]

    assert by_event["strike.issued"]["send"] is False  # nur protokollieren
    assert all(o["reservation_id"] for o in out)


def test_api_driven_events_render(flow):
    svc, _, jonas = flow
    booked = svc.book(jonas.id, "type-BH", "hub-NK", RentalType.DAY, berlin(2026, 11, 30, 10), NOW)
    rid = booked.reservation.id
    t48 = berlin(2026, 11, 28, 11)
    reminder = svc.send_reminder(rid, t48)
    reminder_body = {"event": "reservation.reminder", "changed": True, **svc.details(reminder.reservation, token=reminder.token)}

    auto = svc.auto_cancel(rid, berlin(2026, 11, 29, 11))
    auto_body = {"event": "reservation.auto_cancelled", "changed": True, **svc.details(auto.reservation)}

    soon = svc.book(jonas.id, "type-PS", "hub-TH", RentalType.DAY, berlin(2026, 11, 24, 10), NOW, binding_accepted=True)
    ns = svc.mark_no_show(soon.reservation.id, berlin(2026, 11, 24, 12, 30))
    no_show_body = {
        "event": "reservation.no_show",
        "changed": True,
        **svc.details(ns.reservation),
        "fee": {"amount": str(ns.fee), "currency": "EUR"},
    }

    # WF-02/03/04 schicken an den eigenen Webhook → ebenfalls unter "body"
    out = render([{"body": b} for b in (reminder_body, auto_body, no_show_body)])
    reminder_mail, auto_mail, no_show_mail = out
    assert reminder_mail["send"] and reminder.token in reminder_mail["html"]
    assert "kostenlos" in auto_mail["text"]
    assert "55,00 €" in no_show_mail["html"] and "2 Strike(s)" in no_show_mail["html"]


def test_html_is_escaped():
    body = {
        "event": "reservation.auto_cancelled",
        "customer": {"email": "x@example.com", "full_name": "<script>alert(1)</script>", "strike_text": ""},
        "reservation": {"id": "r1", "code": "HR-X", "start_local": "", "end_local": "", "price": "1"},
        "device": {"name": "Säge"},
        "hub": {"name": "H", "address": "A"},
    }
    (mail,) = render([{"body": body}])
    assert "<script>" not in mail["html"] and "&lt;script&gt;" in mail["html"]


def test_unknown_event_is_logged_not_sent():
    (out,) = render([{"body": {"event": "reservation.picked_up", "reservation": {"id": "r9"}}}])
    assert out["send"] is False and out["reservation_id"] == "r9"
