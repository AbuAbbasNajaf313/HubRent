"""Hub-Terminal-Simulator (Kiosk-Ansicht im Schließfach-Hub).

Abholen: PIN eintippen → das passende Fach öffnet sich.
Rückgabe: Reservierungscode eintippen → das Fach öffnet sich, Gerät hineinlegen.

Kein Login: Am echten Terminal steht der Kunde vor Ort. Schutz gegen PIN-Raten:
höchstens 5 Fehlversuche pro Minute und Terminal (``AttemptLimiter``).
"""
from __future__ import annotations

import math

from flask import Blueprint, abort, render_template, request

from app.domain.errors import DomainError

from . import hubrent, now
from .forms import ActionForm

bp = Blueprint("terminal", __name__, url_prefix="/terminal")

MODES = {"abholen": "Abholen", "rueckgabe": "Rückgabe"}


def _hub_or_404(hub_id: str):
    hub = hubrent().repo.get_hub(hub_id)
    if hub is None or not hub.active:
        abort(404)
    return hub


def _render(hub, mode: str, status: int = 200, **ctx):
    lockers = sorted(hubrent().repo.list_devices(hub_id=hub.id), key=lambda d: d.locker_number)
    key = f"{hub.id}:{mode}"
    return (
        render_template(
            "terminal/kiosk.html",
            hub=hub,
            mode=mode,
            modes=MODES,
            lockers=lockers,
            form=ActionForm(),
            remaining=hubrent().terminal_limiter.remaining(key, now()),
            **ctx,
        ),
        status,
    )


@bp.get("")
def choose():
    hubs = [h for h in hubrent().repo.list_hubs() if h.active]
    return render_template("terminal/choose.html", hubs=hubs)


@bp.get("/<hub_id>")
def kiosk(hub_id: str):
    mode = request.args.get("modus", "abholen")
    return _render(_hub_or_404(hub_id), mode if mode in MODES else "abholen")


def _attempt(hub, mode: str, action):
    """Gemeinsamer Ablauf: Sperre prüfen → Aktion → bei Fehler Fehlversuch zählen."""
    limiter, key, t = hubrent().terminal_limiter, f"{hub.id}:{mode}", now()
    wait = limiter.retry_after(key, t)
    if wait is not None:
        seconds = math.ceil(wait.total_seconds())
        return _render(hub, mode, 429, error=f"Zu viele Fehlversuche. Bitte warte {seconds} Sekunden.", locked=True)
    if not ActionForm().validate_on_submit():
        return _render(hub, mode, 400, error="Sitzung abgelaufen, bitte erneut versuchen.")
    try:
        result = action(t)
    except DomainError as exc:
        limiter.record_failure(key, t)
        return _render(hub, mode, 400, error=str(exc))
    details = hubrent().rentals.details(result.reservation)
    return _render(hub, mode, opened=result.extra["locker_number"], details=details, result=result)


@bp.post("/<hub_id>/abholen")
def pick_up(hub_id: str):
    hub = _hub_or_404(hub_id)
    pin = "".join(ch for ch in request.form.get("pin", "") if ch.isdigit())
    return _attempt(hub, "abholen", lambda t: hubrent().rentals.pick_up(hub.id, pin, t))


@bp.post("/<hub_id>/rueckgabe")
def give_back(hub_id: str):
    hub = _hub_or_404(hub_id)
    code = request.form.get("code", "").strip().upper()
    if code and not code.startswith("HR-"):
        code = "HR-" + code  # Kunde darf "HR-" weglassen
    return _attempt(hub, "rueckgabe", lambda t: hubrent().rentals.return_at_hub(hub.id, code, t))
