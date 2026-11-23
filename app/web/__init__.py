"""Web-Schicht: Blueprints, Login, CSRF, Template-Filter.

Die Routen sind bewusst dünn: Formular lesen → Service aufrufen → Ergebnis anzeigen.
Geschäftsregeln stehen ausschließlich in ``domain/`` und ``services/``.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from flask import Flask, current_app, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, current_user
from flask_wtf.csrf import CSRFError, CSRFProtect

from app.domain.models import Customer, RentalType, ReservationStatus as S

csrf = CSRFProtect()
login_manager = LoginManager()

STATUS_LABELS = {
    S.PENDING: ("Unbestätigt", "bg-amber-100 text-amber-800"),
    S.CONFIRMED: ("Bestätigt", "bg-emerald-100 text-emerald-800"),
    S.PICKED_UP: ("Abgeholt", "bg-sky-100 text-sky-800"),
    S.RETURNED: ("Zurückgegeben", "bg-stone-200 text-stone-700"),
    S.CANCELLED_BY_CUSTOMER: ("Storniert", "bg-stone-200 text-stone-700"),
    S.CANCELLED_AUTO: ("Automatisch freigegeben", "bg-stone-200 text-stone-700"),
    S.NO_SHOW: ("Nicht abgeholt", "bg-rose-100 text-rose-800"),
}
RENTAL_LABELS = {
    RentalType.FOUR_HOURS: "4 Stunden",
    RentalType.DAY: "Tagesmiete",
    RentalType.WEEKEND: "Wochenende",
}


class LoginUser(UserMixin):
    """Flask-Login braucht ein Objekt mit ``id``; dahinter steckt der Domain-Kunde."""

    def __init__(self, customer: Customer) -> None:
        self.customer = customer
        self.id = customer.id


def hubrent():
    return current_app.extensions["hubrent"]


def now() -> datetime:
    return hubrent().clock()


def customer() -> Customer:
    return current_user.customer


def euro(value: Decimal | str | float | None) -> str:
    """16.5 → "16,50 €" (deutsches Format)."""
    amount = Decimal(str(value or 0)).quantize(Decimal("0.01"))
    whole, cents = f"{amount:,.2f}".split(".")
    return f"{whole.replace(',', '.')},{cents} €"


def local_dt(value: datetime | None, fmt: str = "%d.%m.%Y, %H:%M Uhr") -> str:
    if value is None:
        return ""
    return value.astimezone(hubrent().config.rules.timezone).strftime(fmt)


WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def local_day(value: datetime) -> str:
    local = value.astimezone(hubrent().config.rules.timezone)
    return f"{WEEKDAYS[local.weekday()]}, {local:%d.%m.%Y}"


def safe_next(target: str | None) -> str | None:
    """Nur relative Pfade erlauben, sonst wäre ?next=https://boese.example ein offener Redirect."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


def init_web(app: Flask) -> None:
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Bitte melde dich an."
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id: str):
        c = app.extensions["hubrent"].repo.get_customer(user_id)
        return LoginUser(c) if c else None

    app.jinja_env.filters.update(euro=euro, local=local_dt, day=local_day)
    # Konstanten als Globals: auch in importierten Makros sichtbar (Context-Prozessoren nicht).
    app.jinja_env.globals.update(STATUS_LABELS=STATUS_LABELS, RENTAL_LABELS=RENTAL_LABELS, S=S, RentalType=RentalType)

    @app.context_processor
    def globals_():
        return {
            "demo_mode": hubrent().config.rules.demo_mode,
            "data_source": hubrent().config.repository,
        }

    from . import account, auth, catalog, internal_api, reservation_links, terminal

    for bp in (auth.bp, catalog.bp, account.bp, reservation_links.bp, internal_api.bp, terminal.bp):
        app.register_blueprint(bp)

    @app.errorhandler(404)
    def not_found(_):
        return render_template("message.html", title="Nicht gefunden", text="Diese Seite gibt es nicht."), 404

    @app.errorhandler(CSRFError)
    def csrf_error(_):
        flash("Das Formular war abgelaufen. Bitte versuche es noch einmal.", "error")
        return redirect(safe_next(request.path) or url_for("catalog.index"))
