"""Startseite, Gerätekatalog, Detailseite mit Live-Preis und Buchung."""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from wtforms.fields.choices import SelectChoice

from app.domain.errors import DomainError
from app.domain.models import RentalType
from app.domain.pricing import next_possible_start, upcoming_weekend_starts
from app.repository.airtable_schema import CATEGORIES

from . import customer, hubrent, local_day, now
from .forms import BookingForm

bp = Blueprint("catalog", __name__)


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/geraete")
def devices():
    hub_id = request.args.get("hub") or None
    category = request.args.get("kategorie") or None
    entries = hubrent().rentals.catalog(now(), hub_id=hub_id, category=category)
    return render_template(
        "catalog/list.html",
        entries=entries,
        hubs=hubrent().repo.list_hubs(),
        categories=CATEGORIES,
        selected_hub=hub_id,
        selected_category=category,
    )


def _booking_form(device_type_id: str, data=None) -> BookingForm:
    """Formular mit Hub-Auswahl, Startvorschlag und den nächsten Wochenenden."""
    rules = hubrent().config.rules
    # Das HTMX-Partial ist ein GET ohne Wirkung und braucht kein CSRF-Token.
    form = BookingForm(formdata=data, meta={"csrf": False} if data is request.args else {})
    form.device_type_id.data = form.device_type_id.data or device_type_id
    form.hub_id.choices = [SelectChoice(h.id, h.name) for h in hubrent().repo.list_hubs() if h.active]
    form.weekend_start.choices = [
        SelectChoice(s.isoformat(), f"{local_day(s)}, 14:00 Uhr bis Mo 10:00 Uhr") for s in upcoming_weekend_starts(now(), rules)
    ]
    if not form.start.data:
        form.start.data = next_possible_start(now(), rules).strftime("%Y-%m-%dT%H:%M")
    return form


@bp.route("/geraete/<type_id>")
def device_detail(type_id: str):
    device_type = hubrent().repo.get_device_type(type_id)
    if device_type is None:
        abort(404)
    form = _booking_form(type_id, data=None)
    entry = next((e for e in hubrent().rentals.catalog(now()) if e.device_type.id == type_id), None)
    if request.args.get("hub"):
        form.hub_id.data = request.args["hub"]
    elif entry and entry.free_total:
        # Hub vorauswählen, an dem gerade etwas frei ist (nicht den mit dem Gerät in Wartung)
        form.hub_id.data = max(entry.free_by_hub, key=entry.free_by_hub.get)
    rules = hubrent().config.rules
    return render_template(
        "catalog/detail.html",
        device_type=device_type,
        entry=entry,
        form=form,
        min_start=next_possible_start(now(), rules).strftime("%Y-%m-%dT%H:%M"),
        step_seconds=int(rules.start_granularity.total_seconds()),
        high_strikes=current_user.is_authenticated and customer().strikes >= 3,
    )


@bp.route("/api/verfuegbarkeit")
def availability():
    """HTMX-Partial: Preis, Verfügbarkeit und Hinweis auf Verbindlichkeit für die aktuelle Auswahl."""
    form = _booking_form(request.args.get("device_type_id", ""), data=request.args)
    try:
        rental_type = form.rental_type_enum()
        quote = hubrent().rentals.quote(
            form.device_type_id.data,
            form.hub_id.data,
            rental_type,
            form.start_datetime(hubrent().config.rules.timezone),
            now(),
            days=(form.days.data or 1) if rental_type is RentalType.DAY else 1,
        )
    except DomainError as exc:
        return render_template("catalog/_quote.html", error=str(exc), form=form)
    return render_template("catalog/_quote.html", quote=quote, form=form, rental_type=rental_type)


@bp.route("/buchen", methods=["POST"])
@login_required
def book():
    form = _booking_form(request.form.get("device_type_id", ""), data=request.form)
    type_id = form.device_type_id.data
    if not form.validate():
        flash(" ".join(e for errors in form.errors.values() for e in errors), "error")
        return redirect(url_for("catalog.device_detail", type_id=type_id))
    try:
        rental_type = form.rental_type_enum()
        result = hubrent().rentals.book(
            customer().id,
            type_id,
            form.hub_id.data,
            rental_type,
            form.start_datetime(hubrent().config.rules.timezone),
            now(),
            days=(form.days.data or 1) if rental_type is RentalType.DAY else 1,
            binding_accepted=form.binding.data,
        )
    except DomainError as exc:  # auch NotAvailable, InvalidBookingTime
        flash(str(exc), "error")
        return redirect(url_for("catalog.device_detail", type_id=type_id, hub=form.hub_id.data))
    # Post/Redirect/Get: Neu laden der Erfolgsseite bucht nicht ein zweites Mal.
    return redirect(url_for("account.reservation", reservation_id=result.reservation.id, neu=1))
