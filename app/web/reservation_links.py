"""Bestätigen und Stornieren per Link aus der Mail (ohne Login).

GET zeigt nur an, was passieren würde. Erst der Klick auf den Button (POST mit
CSRF-Token) ändert den Status. Grund: Mailprogramme und Virenscanner öffnen Links
manchmal automatisch zur Vorschau. Ein GET darf deshalb nie etwas auslösen.
"""
from __future__ import annotations

from flask import Blueprint, render_template

from app.domain.errors import DomainError
from app.domain.models import ReservationStatus as S
from app.domain.rules import can_confirm

from . import hubrent, now
from .account import strike_fee_preview
from .forms import ActionForm

bp = Blueprint("links", __name__, url_prefix="/r")


def _invalid(exc: DomainError):
    return render_template("message.html", title="Link nicht gültig", text=str(exc)), 404


@bp.route("/<token>/bestaetigen", methods=["GET", "POST"])
def confirm(token: str):
    svc = hubrent().rentals
    form = ActionForm()
    try:
        r = svc.reservation_for_token(token, now())
        if form.validate_on_submit():
            res = svc.confirm(token, now())
            return render_template("links/confirmed.html", details=svc.details(res.reservation), changed=res.changed)
    except DomainError as exc:
        return _invalid(exc)
    if r.status is S.CONFIRMED:
        return render_template("links/confirmed.html", details=svc.details(r), changed=False)
    return render_template(
        "links/confirm.html",
        details=svc.details(r),
        reservation=r,
        allowed=can_confirm(r, now(), hubrent().config.rules),
        form=form,
    )


@bp.route("/<token>/stornieren", methods=["GET", "POST"])
def cancel(token: str):
    svc = hubrent().rentals
    form = ActionForm()
    try:
        r = svc.reservation_for_token(token, now())
        assessment = svc.assess_cancellation(token, now())
        if form.validate_on_submit():
            res = svc.cancel(token, now())
            return render_template("links/cancelled.html", details=svc.details(res.reservation), result=res)
    except DomainError as exc:
        return _invalid(exc)
    customer = hubrent().repo.get_customer(r.customer_id)
    return render_template(
        "links/cancel.html",
        details=svc.details(r),
        reservation=r,
        assessment=assessment,
        fee=strike_fee_preview(customer.strikes, r.daily_rate_snapshot),
        form=form,
    )
