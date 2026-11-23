"""Abnahmekriterium: Im DEMO_MODE läuft der komplette Ablauf in unter 10 Minuten.

Mit den empfohlenen Demo-Werten aus docs/demo-script.md:
DEMO_MODE=true, REMINDER_HOURS_BEFORE=6, CONFIRM_DEADLINE_HOURS_BEFORE=3, LATE_CANCEL_HOURS_BEFORE=3
→ Erinnerung 6 min, Bestätigungsfrist 3 min vor Start; Abholfenster 30 s vor bis 2 min nach Start.
"""
from datetime import timedelta

from app.domain.models import RentalType, ReservationStatus as S
from app.domain.pricing import next_possible_start
from app.domain.rule_config import RuleConfig
from app.repository.memory_repo import InMemoryRepository
from app.seed_data import build_seed, load_into_memory
from app.services.events import RecordingPublisher
from app.services.rentals import RentalService

from .conftest import berlin

DEMO_ENV = {
    "DEMO_MODE": "true",
    "REMINDER_HOURS_BEFORE": "6",
    "CONFIRM_DEADLINE_HOURS_BEFORE": "3",
    "LATE_CANCEL_HOURS_BEFORE": "3",
}
T0 = berlin(2026, 11, 23, 12, 0)


def setup():
    rules = RuleConfig.from_env(DEMO_ENV)
    repo = InMemoryRepository()
    seed = build_seed(password_hasher=lambda p: "h")
    load_into_memory(repo, seed)
    pub = RecordingPublisher()
    svc = RentalService(repo, rules, pub)
    customer = repo.get_customer_by_email(seed.customers[1].email)  # Jonas, 1 Strike
    return rules, repo, pub, svc, customer


def test_demo_rules():
    rules = RuleConfig.from_env(DEMO_ENV)
    assert rules.reminder_before == timedelta(minutes=6)
    assert rules.confirm_deadline_before == timedelta(minutes=3)
    assert rules.pickup_window_before == timedelta(seconds=30)
    assert rules.pickup_window_after == timedelta(minutes=2)
    assert next_possible_start(T0, rules) == berlin(2026, 11, 23, 12, 1)  # Minutenraster, 30 s Vorlauf


def test_happy_path_under_ten_minutes():
    rules, repo, pub, svc, jonas = setup()
    start = T0 + timedelta(minutes=7)  # > 6 min → PENDING
    booked = svc.book(jonas.id, "type-BH", "hub-NK", RentalType.FOUR_HOURS, start, T0)
    assert booked.reservation.status is S.PENDING

    t = T0 + timedelta(minutes=1, seconds=30)  # n8n-Cron (1/min) findet die Erinnerung
    reminder = svc.send_reminder(booked.reservation.id, t)
    assert reminder.changed

    t += timedelta(minutes=1)  # Kunde klickt in der Mail auf "Bestätigen"
    confirmed = svc.confirm(reminder.token, t)
    assert confirmed.reservation.status is S.CONFIRMED

    t = start  # Abholung am Terminal
    picked = svc.pick_up("hub-NK", confirmed.reservation.pin, t)
    assert picked.reservation.status is S.PICKED_UP

    t += timedelta(minutes=1)  # Rückgabe
    returned = svc.return_at_hub("hub-NK", booked.reservation.code, t)
    assert returned.reservation.status is S.RETURNED
    assert t - T0 < timedelta(minutes=10)


def test_no_show_flow_under_ten_minutes():
    rules, repo, pub, svc, jonas = setup()
    start = T0 + timedelta(minutes=2)  # ≤ 6 min → sofort verbindlich
    res = svc.book(jonas.id, "type-PS", "hub-TH", RentalType.DAY, start, T0, binding_accepted=True).reservation
    t = start + timedelta(minutes=3)  # Abholfenster (2 min) vorbei, nächster Cron-Lauf
    ns = svc.mark_no_show(res.id, t)
    assert ns.changed and ns.customer.strikes == 2 and str(ns.fee) == "55.00"
    assert t - T0 < timedelta(minutes=10)


def test_auto_cancel_flow_under_ten_minutes():
    rules, repo, pub, svc, jonas = setup()
    start = T0 + timedelta(minutes=8)
    rid = svc.book(jonas.id, "type-BH", "hub-NK", RentalType.FOUR_HOURS, start, T0).reservation.id
    t = start - timedelta(minutes=3)  # Bestätigungsfrist erreicht
    auto = svc.auto_cancel(rid, t)
    assert auto.changed and auto.reservation.status is S.CANCELLED_AUTO
    assert repo.get_customer(jonas.id).strikes == 1  # kein neuer Strike
    assert t - T0 < timedelta(minutes=10)
