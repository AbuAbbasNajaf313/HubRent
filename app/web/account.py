"""Mein Konto: Reservierungen, Strike-Stand, Bestätigen und Stornieren (eingeloggt)."""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.domain.errors import DomainError
from app.domain.strikes import calculate_fee

from . import customer, hubrent, now
from .forms import ActionForm

bp = Blueprint("account", __name__, url_prefix="/konto")


def strike_fee_preview(strikes_now: int, daily_rate) -> object:
    """Gebühr, die bei einem weiteren Strike fällig würde (für den Storno-Hinweis)."""
    return calculate_fee(strikes_now + 1, daily_rate)


@bp.route("")
@login_required
def overview():
    ov = hubrent().rentals.account_overview(customer().id, now())
    return render_template("account/overview.html", ov=ov, form=ActionForm(), fee_preview=strike_fee_preview)


@bp.route("/reservierung/<reservation_id>")
@login_required
def reservation(reservation_id: str):
    ov = hubrent().rentals.account_overview(customer().id, now())
    item = next((i for i in ov.active + ov.past if i.reservation.id == reservation_id), None)
    if item is None:
        abort(404)  # gibt es nicht oder gehört jemand anderem: gleiche Antwort
    return render_template(
        "account/reservation.html",
        item=item,
        ov=ov,
        is_new=request.args.get("neu") == "1",
        form=ActionForm(),
        fee_preview=strike_fee_preview,
    )


@bp.route("/reservierung/<reservation_id>/bestaetigen", methods=["POST"])
@login_required
def confirm(reservation_id: str):
    if ActionForm().validate_on_submit():
        try:
            res = hubrent().rentals.confirm_by_customer(reservation_id, customer().id, now())
            flash(
                f"Bestätigt! Deine PIN lautet {res.reservation.pin}." if res.changed else "War schon bestätigt.",
                "success",
            )
        except DomainError as exc:
            flash(str(exc), "error")
    return redirect(url_for("account.reservation", reservation_id=reservation_id))


@bp.route("/reservierung/<reservation_id>/stornieren", methods=["POST"])
@login_required
def cancel(reservation_id: str):
    if ActionForm().validate_on_submit():
        try:
            res = hubrent().rentals.cancel_by_customer(reservation_id, customer().id, now())
            flash(f"Storniert. {res.message}", "success" if res.extra["free_of_charge"] else "error")
        except DomainError as exc:
            flash(str(exc), "error")
    return redirect(url_for("account.overview"))
