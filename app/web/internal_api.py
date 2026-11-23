"""Interne API für n8n.

n8n entscheidet, *wann* etwas fällig sein könnte (Cron + Airtable-Suche), und ruft
dann diese Endpunkte auf. Flask entscheidet, *ob* der Schritt jetzt wirklich
zulässig ist. Ist nichts zu tun, kommt ``200`` mit ``"changed": false``.

Idempotenz: Ein Cron-Job kann denselben Datensatz zweimal finden, n8n kann nach
einem Timeout wiederholen. Ein zweiter Aufruf ändert dann nichts mehr, es gibt
also nie doppelte Strikes, Gebühren oder Erinnerungen.

Absicherung: Header ``X-Internal-Secret`` muss ``INTERNAL_API_SECRET`` entsprechen.
Der Vergleich läuft mit ``hmac.compare_digest``, damit die Antwortzeit nichts über
das Secret verrät. Ohne konfiguriertes Secret ist die API abgeschaltet (503).
"""
from __future__ import annotations

import hmac
from decimal import Decimal
from typing import Callable

from flask import Blueprint, jsonify, request

from app.domain.errors import DomainError, NotFound

from . import csrf, hubrent, now

bp = Blueprint("internal_api", __name__, url_prefix="/api/internal")
csrf.exempt(bp)  # Maschine-zu-Maschine: Schutz über das Shared Secret statt CSRF-Token


@bp.before_request
def require_secret():
    expected = hubrent().config.internal_api_secret
    if not expected:
        return jsonify(error="Interne API ist nicht konfiguriert (INTERNAL_API_SECRET fehlt)."), 503
    given = request.headers.get("X-Internal-Secret", "")
    if not hmac.compare_digest(given.encode(), expected.encode()):
        return jsonify(error="Nicht autorisiert."), 401
    return None


@bp.errorhandler(DomainError)
def domain_error(exc: DomainError):
    status = 404 if isinstance(exc, NotFound) else 409
    return jsonify(error=str(exc)), status


@bp.get("/health")
def health():
    cfg = hubrent().config
    return jsonify(status="ok", repository=cfg.repository, demo_mode=cfg.rules.demo_mode, time=now().isoformat())


def _respond(action: Callable[[str, object], object], reservation_id: str):
    """Führt eine Service-Aktion aus und liefert alles, was n8n für die Mail braucht."""
    svc = hubrent().rentals
    result = action(reservation_id, now())
    body = {
        "changed": result.changed,
        "message": result.message,
        # Token (und damit Links) nur, wenn gerade ein neuer erzeugt wurde
        **svc.details(result.reservation, token=result.token if result.changed else None),
        "fee": {"amount": str(result.fee.quantize(Decimal("0.01"))), "currency": "EUR"},
    }
    return jsonify(body)


@bp.post("/reservations/<reservation_id>/reminder-sent")
def reminder_sent(reservation_id: str):
    return _respond(hubrent().rentals.send_reminder, reservation_id)


@bp.post("/reservations/<reservation_id>/auto-cancel")
def auto_cancel(reservation_id: str):
    return _respond(hubrent().rentals.auto_cancel, reservation_id)


@bp.post("/reservations/<reservation_id>/no-show")
def no_show(reservation_id: str):
    return _respond(hubrent().rentals.mark_no_show, reservation_id)
