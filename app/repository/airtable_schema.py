"""Das Airtable-Schema von HubRent als Python-Daten.

Eine einzige Quelle für Tabellen- und Feldnamen: Das Setup-Skript legt daraus die
Tabellen an, das ``AirtableRepository`` liest und schreibt genau diese Felder.
Ein Tippfehler in einem Feldnamen fällt so nicht erst in Airtable auf.

Abweichungen von der Spezifikation (Abschnitt 6), weil die Airtable-API diese
Feldtypen beim Anlegen nicht zuverlässig unterstützt (Formel, Autonumber,
"Created time" gelten in der API-Doku als read-only):

- ``reservation_code`` ist Text. Flask erzeugt den Code (``HR-7K3QXM``).
- ``created_at`` ist ein normales Datumsfeld, Flask schreibt es beim Anlegen.
- ``device_id``, ``hub_id``, ``customer_id`` … sind Textfelder mit der Record-ID,
  zusätzlich zur Verknüpfung. Sie ersetzen die RECORD_ID()-Formeln und machen
  Filter in Flask und n8n einfach: ``{device_id} = 'rec…'``.
- Primärfelder sind Text (auch ``email``), weil die API nicht dokumentiert,
  welche Typen als Primärfeld erlaubt sind.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.models import DeviceStatus, RentalType, ReservationStatus, ViolationType

HUBS = "Hubs"
DEVICE_TYPES = "DeviceTypes"
DEVICES = "Devices"
CUSTOMERS = "Customers"
RESERVATIONS = "Reservations"
STRIKE_EVENTS = "StrikeEvents"
FEES = "Fees"
EVENT_LOG = "EventLog"

CATEGORIES = ["Bohren", "Reinigen", "Schleifen", "Sägen", "Garten", "Renovieren"]
FEE_STATUSES = ["OPEN", "PAID", "WAIVED"]
STRIKE_EVENT_TYPES = [v.value for v in ViolationType] + ["REDUCTION"]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: str
    options: dict[str, Any] | None = None

    def to_api(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "type": self.type}
        if self.options is not None:
            out["options"] = self.options
        return out


@dataclass(frozen=True)
class LinkSpec:
    name: str
    target: str  # Tabellenname


@dataclass(frozen=True)
class TableSpec:
    name: str
    fields: list[FieldSpec]  # erstes Feld = Primärfeld
    links: list[LinkSpec] = field(default_factory=list)


# --- Feld-Bausteine ---------------------------------------------------------------

def text(name: str) -> FieldSpec:
    return FieldSpec(name, "singleLineText")


def long_text(name: str) -> FieldSpec:
    return FieldSpec(name, "multilineText")


def number(name: str) -> FieldSpec:
    return FieldSpec(name, "number", {"precision": 0})


def euro(name: str) -> FieldSpec:
    return FieldSpec(name, "currency", {"precision": 2, "symbol": "€"})


def checkbox(name: str) -> FieldSpec:
    return FieldSpec(name, "checkbox", {"color": "greenBright", "icon": "check"})


def url(name: str) -> FieldSpec:
    return FieldSpec(name, "url")


def date_time(name: str) -> FieldSpec:
    # Gespeichert wird immer UTC. timeZone steuert nur die Anzeige in der Airtable-Oberfläche.
    return FieldSpec(
        name,
        "dateTime",
        {"dateFormat": {"name": "european"}, "timeFormat": {"name": "24hour"}, "timeZone": "Europe/Berlin"},
    )


def select(name: str, choices: list[str]) -> FieldSpec:
    return FieldSpec(name, "singleSelect", {"choices": [{"name": c} for c in choices]})


# --- Tabellen (Reihenfolge = Anlegereihenfolge) ---------------------------------

TABLES: list[TableSpec] = [
    TableSpec(HUBS, [text("name"), text("address"), text("store_name"), checkbox("active")]),
    TableSpec(
        DEVICE_TYPES,
        [text("name"), select("category", CATEGORIES), long_text("description"), euro("daily_rate"), url("image_url")],
    ),
    TableSpec(
        DEVICES,
        [
            text("device_code"),
            number("locker_number"),
            select("status", [s.value for s in DeviceStatus]),
            text("device_type_id"),
            text("hub_id"),
        ],
        [LinkSpec("device_type", DEVICE_TYPES), LinkSpec("hub", HUBS)],
    ),
    TableSpec(
        CUSTOMERS,
        [
            text("email"),
            text("full_name"),
            text("password_hash"),
            number("strikes"),
            number("clean_streak"),
            date_time("terms_accepted_at"),
            date_time("created_at"),
        ],
    ),
    TableSpec(
        RESERVATIONS,
        [
            text("reservation_code"),
            select("rental_type", [t.value for t in RentalType]),
            date_time("start_at"),
            date_time("end_at"),
            euro("price"),
            euro("daily_rate_snapshot"),
            select("status", [s.value for s in ReservationStatus]),
            text("token_hash"),
            date_time("token_expires_at"),
            text("pin"),
            date_time("reminder_sent_at"),
            date_time("confirmed_at"),
            date_time("cancelled_at"),
            date_time("picked_up_at"),
            date_time("returned_at"),
            date_time("created_at"),
            text("customer_id"),
            text("device_id"),
        ],
        [LinkSpec("customer", CUSTOMERS), LinkSpec("device", DEVICES)],
    ),
    TableSpec(
        STRIKE_EVENTS,
        [
            text("label"),
            select("type", STRIKE_EVENT_TYPES),
            number("strikes_after"),
            euro("fee_amount"),
            date_time("created_at"),
            text("customer_id"),
            text("reservation_id"),
        ],
        [LinkSpec("customer", CUSTOMERS), LinkSpec("reservation", RESERVATIONS)],
    ),
    TableSpec(
        FEES,
        [
            text("label"),
            euro("amount"),
            select("reason", [v.value for v in ViolationType]),
            select("status", FEE_STATUSES),
            date_time("created_at"),
            text("customer_id"),
            text("reservation_id"),
        ],
        [LinkSpec("customer", CUSTOMERS), LinkSpec("reservation", RESERVATIONS)],
    ),
    TableSpec(
        EVENT_LOG,
        [
            text("event_type"),
            select("source", ["flask", "n8n"]),
            long_text("payload"),
            date_time("created_at"),
            text("reservation_id"),
        ],
        [LinkSpec("reservation", RESERVATIONS)],
    ),
]


def table(name: str) -> TableSpec:
    return next(t for t in TABLES if t.name == name)
