"""Formulare (Flask-WTF bringt den CSRF-Schutz mit).

Die Formulare prüfen nur Form und Format (Pflichtfeld, Zahl, Datum lesbar).
Ob eine Buchung *erlaubt* ist, entscheidet ausschließlich der Service.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, HiddenField, IntegerField, PasswordField, RadioField, SelectField, StringField
from wtforms.fields.choices import SelectChoice
from wtforms.validators import DataRequired, EqualTo, NumberRange, Optional

from app.domain.errors import InvalidBookingTime
from app.domain.models import RentalType


class RegisterForm(FlaskForm):
    full_name = StringField("Name", validators=[DataRequired("Bitte gib deinen Namen ein.")])
    email = EmailField("E-Mail", validators=[DataRequired("Bitte gib deine E-Mail-Adresse ein.")])
    password = PasswordField("Passwort (mind. 8 Zeichen)", validators=[DataRequired("Bitte wähle ein Passwort.")])
    password_repeat = PasswordField(
        "Passwort wiederholen", validators=[EqualTo("password", "Die Passwörter stimmen nicht überein.")]
    )
    terms = BooleanField("Ich akzeptiere die AGB und die Fair-Use-Regeln (Strike-System).")


class LoginForm(FlaskForm):
    email = EmailField("E-Mail", validators=[DataRequired("Bitte gib deine E-Mail-Adresse ein.")])
    password = PasswordField("Passwort", validators=[DataRequired("Bitte gib dein Passwort ein.")])
    next = HiddenField()


class ActionForm(FlaskForm):
    """Leeres Formular für Buttons, die etwas ändern (POST + CSRF-Token)."""


class BookingForm(FlaskForm):
    device_type_id = HiddenField(validators=[DataRequired()])
    hub_id = SelectField("Hub", validators=[DataRequired("Bitte wähle einen Hub.")])
    rental_type = RadioField(
        "Mietart",
        choices=[
            SelectChoice(RentalType.FOUR_HOURS.value, "4 Stunden"),
            SelectChoice(RentalType.DAY.value, "Tage"),
            SelectChoice(RentalType.WEEKEND.value, "Wochenende"),
        ],
        default=RentalType.FOUR_HOURS.value,
    )
    start = StringField("Start", validators=[Optional()])  # datetime-local, z. B. 2026-11-30T10:00
    weekend_start = SelectField("Wochenende", validators=[Optional()], validate_choice=False)
    days = IntegerField("Anzahl Tage", default=1, validators=[Optional(), NumberRange(1, 14, "1 bis 14 Tage.")])
    binding = BooleanField("Ich buche verbindlich. Eine Stornierung ist ab sofort nur noch mit Strike möglich.")

    def rental_type_enum(self) -> RentalType:
        try:
            return RentalType(self.rental_type.data)
        except ValueError as exc:
            raise InvalidBookingTime("Bitte wähle eine Mietart.") from exc

    def start_datetime(self, tz: ZoneInfo) -> datetime:
        """Liest den Start in lokaler Zeit (Europe/Berlin) und macht ihn zeitzonenbewusst."""
        raw = self.weekend_start.data if self.rental_type_enum() is RentalType.WEEKEND else self.start.data
        if not raw:
            raise InvalidBookingTime("Bitte wähle einen Starttermin.")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise InvalidBookingTime("Der Starttermin ist nicht lesbar.") from exc
        return parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed.astimezone(tz)
