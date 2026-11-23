"""Statusmaschine und Fristen einer Reservierung.

Die Statusmaschine ist wie eine Ablaufsteuerung an einer Maschine: Jeder Schritt
darf nur aus bestimmten Zuständen heraus erfolgen. Ein Gerät, das schon
zurückgegeben wurde, kann nicht mehr als No-Show markiert werden, egal wer es
versucht (Nutzer, n8n, Admin).

Alle Funktionen bekommen ``now`` als Parameter (Dependency Injection der Uhr).
Dadurch sind sie ohne Tricks testbar: Ein Test kann einfach "jetzt = Freitag 13:59"
übergeben.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .errors import InvalidTransition
from .models import Reservation, ReservationStatus as S
from .rule_config import RuleConfig

ALLOWED_TRANSITIONS: dict[S, frozenset[S]] = {
    S.PENDING: frozenset({S.CONFIRMED, S.CANCELLED_BY_CUSTOMER, S.CANCELLED_AUTO}),
    S.CONFIRMED: frozenset({S.PICKED_UP, S.CANCELLED_BY_CUSTOMER, S.NO_SHOW}),
    S.PICKED_UP: frozenset({S.RETURNED}),
    S.RETURNED: frozenset(),
    S.CANCELLED_BY_CUSTOMER: frozenset(),
    S.CANCELLED_AUTO: frozenset(),
    S.NO_SHOW: frozenset(),
}

FINAL_STATUSES = frozenset(s for s, targets in ALLOWED_TRANSITIONS.items() if not targets)


def can_transition(current: S, target: S) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def transition(reservation: Reservation, target: S) -> None:
    """Setzt den neuen Status oder wirft InvalidTransition."""
    if not can_transition(reservation.status, target):
        raise InvalidTransition(f"{reservation.status.value} → {target.value} ist nicht erlaubt.")
    reservation.status = target


def initial_status(start: datetime, now: datetime, rules: RuleConfig) -> S:
    """Kurzfristige Buchungen (≤ 48 h) sind sofort verbindlich."""
    return S.CONFIRMED if start - now <= rules.reminder_before else S.PENDING


# --- Fristen -----------------------------------------------------------------

def reminder_due(r: Reservation, now: datetime, rules: RuleConfig) -> bool:
    return (
        r.status is S.PENDING
        and r.reminder_sent_at is None
        and now >= r.start_at - rules.reminder_before
        and now < r.start_at - rules.confirm_deadline_before
    )


def can_confirm(r: Reservation, now: datetime, rules: RuleConfig) -> bool:
    return r.status is S.PENDING and now < r.start_at - rules.confirm_deadline_before


def auto_cancel_due(r: Reservation, now: datetime, rules: RuleConfig) -> bool:
    return r.status is S.PENDING and now >= r.start_at - rules.confirm_deadline_before


def pickup_window(r: Reservation, rules: RuleConfig) -> tuple[datetime, datetime]:
    return r.start_at - rules.pickup_window_before, r.start_at + rules.pickup_window_after


def can_pick_up(r: Reservation, now: datetime, rules: RuleConfig) -> bool:
    opens, closes = pickup_window(r, rules)
    return r.status is S.CONFIRMED and opens <= now <= closes


def no_show_due(r: Reservation, now: datetime, rules: RuleConfig) -> bool:
    return r.status is S.CONFIRMED and now > pickup_window(r, rules)[1]


def is_on_time_return(r: Reservation, returned_at: datetime, rules: RuleConfig) -> bool:
    return returned_at <= r.end_at + rules.return_grace


# --- Stornierung ---------------------------------------------------------------

@dataclass(frozen=True)
class CancellationAssessment:
    allowed: bool
    free_of_charge: bool
    reason: str


def assess_cancellation(r: Reservation, now: datetime, rules: RuleConfig) -> CancellationAssessment:
    """Bewertet eine Kundenstornierung, ohne etwas zu verändern.

    Die UI zeigt das Ergebnis *vor* dem Klick an ("kostenlos" oder "Strike"),
    der Service nutzt dieselbe Funktion beim eigentlichen Storno.
    """
    if not can_transition(r.status, S.CANCELLED_BY_CUSTOMER):
        return CancellationAssessment(False, False, "Diese Reservierung kann nicht mehr storniert werden.")
    if r.status is S.PENDING:
        return CancellationAssessment(True, True, "Unbestätigte Reservierungen sind immer kostenlos stornierbar.")
    if now - r.created_at <= rules.cancel_grace_after_booking:
        return CancellationAssessment(True, True, "Kostenlos: Storno kurz nach der Buchung (Kulanz).")
    if now < r.start_at - rules.late_cancel_before:
        return CancellationAssessment(True, True, "Kostenlos: mehr als 24 Stunden vor Mietbeginn.")
    return CancellationAssessment(True, False, "Spätstorno: weniger als 24 Stunden vor Mietbeginn, es gibt einen Strike.")
