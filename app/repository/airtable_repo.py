"""Repository-Implementierung für Airtable (über ``pyairtable``).

Aufbau:
- ``AirtableRepository`` bekommt eine *Tabellen-Fabrik* (Name → Tabelle) injiziert.
  In Produktion ist das ``api.table(base_id, name)``, in Tests eine Fake-Tabelle.
  Gleiches Prinzip wie ``now`` in der Domain: Abhängigkeiten werden übergeben,
  nicht im Code fest verdrahtet.
- Die ``_x_from_record``/``_x_fields``-Funktionen übersetzen zwischen Airtable
  (JSON, float, ISO-Strings, fehlende leere Felder) und der Domain
  (Decimal, zeitzonenbewusste datetimes, Enums).

Rate-Limit: Airtable erlaubt 5 Requests/s pro Base und antwortet sonst mit 429.
``make_retry`` wiederholt solche Anfragen mit exponentiellem Backoff.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Iterable, Protocol

import requests
from pyairtable import Api
from pyairtable.formulas import EQ, OR, Field, match
from urllib3.util.retry import Retry

from app.domain.models import (
    Customer,
    Device,
    DeviceStatus,
    DeviceType,
    Hub,
    RentalType,
    Reservation,
    ReservationStatus,
    ViolationType,
)

from . import airtable_schema as T
from .base import EventLogEntry, Fee, Repository, StrikeEvent

FORMULA_CHUNK = 30  # IDs pro OR(...)-Formel, damit die URL nicht zu lang wird
CENT = Decimal("0.01")


class TableLike(Protocol):
    def all(self, **options: Any) -> list[dict[str, Any]]: ...
    def first(self, **options: Any) -> dict[str, Any] | None: ...
    def get(self, record_id: str) -> dict[str, Any]: ...
    def create(self, fields: dict[str, Any]) -> dict[str, Any]: ...
    def update(self, record_id: str, fields: dict[str, Any]) -> dict[str, Any]: ...


TableFactory = Callable[[str], TableLike]


def make_retry() -> Retry:
    """Retry-Strategie für HTTP 429 (und kurze Verbindungsfehler).

    - ``allowed_methods=None``: auch POST/PATCH wiederholen. Bei 429 hat Airtable
      die Anfrage abgelehnt, ein zweiter Versuch legt also nichts doppelt an.
    - ``read=0``: Kommt die Antwort nach dem Senden nicht an (Timeout), wird *nicht*
      wiederholt. Sonst könnte eine Reservierung doppelt angelegt werden.
    - Backoff 0,5 s, 1 s, 2 s, 4 s …; ein ``Retry-After``-Header hat Vorrang.
    """
    return Retry(
        total=5,
        connect=2,
        read=0,
        status=5,
        backoff_factor=0.5,
        status_forcelist=(429,),
        allowed_methods=None,
        respect_retry_after_header=True,
        raise_on_status=False,
    )


# --- Typ-Umwandlungen -------------------------------------------------------------

def dt_to_airtable(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        raise ValueError("Zeitpunkte müssen zeitzonenbewusst sein (tz-aware).")
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def dt_from_airtable(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def money_from_airtable(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT)


def money_to_airtable(value: Decimal) -> float:
    return float(value)


def _link(record_id: str | None) -> list[str]:
    return [record_id] if record_id else []


def _link_id(fields: dict[str, Any], text_field: str, link_field: str) -> str:
    """Record-ID aus dem Textfeld, zur Sicherheit sonst aus der Verknüpfung."""
    if fields.get(text_field):
        return fields[text_field]
    linked = fields.get(link_field) or []
    return linked[0] if linked else ""


# --- Mapping pro Tabelle -----------------------------------------------------------

def hub_from_record(rec: dict[str, Any]) -> Hub:
    f = rec["fields"]
    return Hub(rec["id"], f.get("name", ""), f.get("address", ""), f.get("store_name", ""), bool(f.get("active")))


def hub_fields(h: Hub) -> dict[str, Any]:
    return {"name": h.name, "address": h.address, "store_name": h.store_name, "active": h.active}


def device_type_from_record(rec: dict[str, Any]) -> DeviceType:
    f = rec["fields"]
    return DeviceType(
        rec["id"],
        f.get("name", ""),
        f.get("category", ""),
        money_from_airtable(f.get("daily_rate")),
        f.get("description", ""),
        f.get("image_url", ""),
    )


def device_type_fields(t: DeviceType) -> dict[str, Any]:
    return {
        "name": t.name,
        "category": t.category,
        "description": t.description,
        "daily_rate": money_to_airtable(t.daily_rate),
        "image_url": t.image_url or None,
    }


def device_from_record(rec: dict[str, Any]) -> Device:
    f = rec["fields"]
    return Device(
        id=rec["id"],
        code=f.get("device_code", ""),
        device_type_id=_link_id(f, "device_type_id", "device_type"),
        hub_id=_link_id(f, "hub_id", "hub"),
        locker_number=int(f.get("locker_number", 0)),
        status=DeviceStatus(f.get("status", DeviceStatus.ACTIVE.value)),
    )


def device_fields(d: Device) -> dict[str, Any]:
    return {
        "device_code": d.code,
        "device_type": _link(d.device_type_id),
        "hub": _link(d.hub_id),
        "device_type_id": d.device_type_id,
        "hub_id": d.hub_id,
        "locker_number": d.locker_number,
        "status": d.status.value,
    }


def customer_from_record(rec: dict[str, Any]) -> Customer:
    f = rec["fields"]
    return Customer(
        id=rec["id"],
        email=f.get("email", ""),
        full_name=f.get("full_name", ""),
        password_hash=f.get("password_hash", ""),
        strikes=int(f.get("strikes", 0)),
        clean_streak=int(f.get("clean_streak", 0)),
        terms_accepted_at=dt_from_airtable(f.get("terms_accepted_at")),
    )


def customer_fields(c: Customer) -> dict[str, Any]:
    return {
        "email": c.email.strip().lower(),
        "full_name": c.full_name,
        "password_hash": c.password_hash,
        "strikes": c.strikes,
        "clean_streak": c.clean_streak,
        "terms_accepted_at": dt_to_airtable(c.terms_accepted_at),
    }


_RESERVATION_TIMES = (
    "start_at",
    "end_at",
    "token_expires_at",
    "reminder_sent_at",
    "confirmed_at",
    "cancelled_at",
    "picked_up_at",
    "returned_at",
    "created_at",
)


def reservation_from_record(rec: dict[str, Any]) -> Reservation:
    f = rec["fields"]
    times = {k: dt_from_airtable(f.get(k)) for k in _RESERVATION_TIMES}
    return Reservation(
        id=rec["id"],
        code=f.get("reservation_code", ""),
        customer_id=_link_id(f, "customer_id", "customer"),
        device_id=_link_id(f, "device_id", "device"),
        rental_type=RentalType(f["rental_type"]),
        price=money_from_airtable(f.get("price")),
        daily_rate_snapshot=money_from_airtable(f.get("daily_rate_snapshot")),
        status=ReservationStatus(f["status"]),
        token_hash=f.get("token_hash", ""),
        pin=f.get("pin", ""),
        **times,
    )


def reservation_fields(r: Reservation) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "reservation_code": r.code,
        "customer": _link(r.customer_id),
        "device": _link(r.device_id),
        "customer_id": r.customer_id,
        "device_id": r.device_id,
        "rental_type": r.rental_type.value,
        "price": money_to_airtable(r.price),
        "daily_rate_snapshot": money_to_airtable(r.daily_rate_snapshot),
        "status": r.status.value,
        "token_hash": r.token_hash,
        "pin": r.pin,
    }
    # None wird mitgeschickt, damit ein Update ein Feld auch wieder leeren kann.
    fields.update({k: dt_to_airtable(getattr(r, k)) for k in _RESERVATION_TIMES})
    return fields


# --- Repository ---------------------------------------------------------------------

class AirtableRepository(Repository):
    def __init__(self, tables: TableFactory) -> None:
        self._factory = tables
        self._cache: dict[str, TableLike] = {}

    @classmethod
    def from_credentials(cls, token: str, base_id: str, timeout: tuple[float, float] = (3, 10)) -> "AirtableRepository":
        api = Api(token, timeout=timeout, retry_strategy=make_retry())
        return cls(lambda name: api.table(base_id, name))

    # Hilfen
    def _t(self, name: str) -> TableLike:
        if name not in self._cache:
            self._cache[name] = self._factory(name)
        return self._cache[name]

    def _get(self, table: str, record_id: str) -> dict[str, Any] | None:
        if not record_id or not record_id.startswith("rec"):
            return None  # z. B. Seed-Schlüssel oder leere ID: in Airtable gibt es sie nicht
        try:
            return self._t(table).get(record_id)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in (403, 404):
                return None  # Airtable meldet unbekannte IDs je nach Fall mit 403 oder 404
            raise

    def _where(self, table: str, **equals: Any) -> list[dict[str, Any]]:
        return self._t(table).all(formula=match(equals))

    def _create(self, table: str, fields: dict[str, Any]) -> dict[str, Any]:
        # Beim Anlegen leere Werte weglassen (bei Updates dagegen mitschicken, um zu leeren).
        return self._t(table).create({k: v for k, v in fields.items() if v not in (None, "", [])})

    @staticmethod
    def _now() -> datetime:
        # Nur für Protokollfelder (created_at). Fachliche Zeitpunkte kommen immer als ``now`` vom Service.
        return datetime.now(timezone.utc)

    # Stammdaten
    def get_hub(self, hub_id):
        rec = self._get(T.HUBS, hub_id)
        return hub_from_record(rec) if rec else None

    def list_hubs(self):
        return [hub_from_record(r) for r in self._t(T.HUBS).all()]

    def get_device_type(self, type_id):
        rec = self._get(T.DEVICE_TYPES, type_id)
        return device_type_from_record(rec) if rec else None

    def list_device_types(self):
        return [device_type_from_record(r) for r in self._t(T.DEVICE_TYPES).all()]

    def get_device(self, device_id):
        rec = self._get(T.DEVICES, device_id)
        return device_from_record(rec) if rec else None

    def list_devices(self, device_type_id=None, hub_id=None):
        equals = {}
        if device_type_id:
            equals["device_type_id"] = device_type_id
        if hub_id:
            equals["hub_id"] = hub_id
        records = self._where(T.DEVICES, **equals) if equals else self._t(T.DEVICES).all()
        return [device_from_record(r) for r in records]

    # Kunden
    def get_customer(self, customer_id):
        rec = self._get(T.CUSTOMERS, customer_id)
        return customer_from_record(rec) if rec else None

    def get_customer_by_email(self, email):
        rec = self._t(T.CUSTOMERS).first(formula=match({"email": email.strip().lower()}))
        return customer_from_record(rec) if rec else None

    def add_customer(self, customer):
        fields = customer_fields(customer)
        fields["created_at"] = dt_to_airtable(self._now())
        return customer_from_record(self._create(T.CUSTOMERS, fields))

    def update_customer(self, customer):
        self._t(T.CUSTOMERS).update(customer.id, customer_fields(customer))

    # Reservierungen
    def get_reservation(self, reservation_id):
        rec = self._get(T.RESERVATIONS, reservation_id)
        return reservation_from_record(rec) if rec else None

    def find_reservation_by_token_hash(self, token_hash):
        if not token_hash:
            return None
        rec = self._t(T.RESERVATIONS).first(formula=match({"token_hash": token_hash}))
        return reservation_from_record(rec) if rec else None

    def find_reservation_by_code(self, code):
        rec = self._t(T.RESERVATIONS).first(formula=match({"reservation_code": code.strip().upper()}))
        return reservation_from_record(rec) if rec else None

    def list_reservations_for_devices(self, device_ids: Iterable[str]):
        ids = list(dict.fromkeys(device_ids))
        result: list[Reservation] = []
        for i in range(0, len(ids), FORMULA_CHUNK):
            chunk = ids[i : i + FORMULA_CHUNK]
            formula = OR(*(EQ(Field("device_id"), d) for d in chunk))
            result += [reservation_from_record(r) for r in self._t(T.RESERVATIONS).all(formula=formula)]
        return result

    def list_reservations_for_customer(self, customer_id):
        records = self._where(T.RESERVATIONS, customer_id=customer_id)
        return sorted((reservation_from_record(r) for r in records), key=lambda r: r.start_at, reverse=True)

    def add_reservation(self, reservation):
        return reservation_from_record(self._create(T.RESERVATIONS, reservation_fields(reservation)))

    def update_reservation(self, reservation):
        self._t(T.RESERVATIONS).update(reservation.id, reservation_fields(reservation))

    # Protokoll / Strikes / Gebühren
    def add_strike_event(self, event: StrikeEvent):
        self._create(
            T.STRIKE_EVENTS,
            {
                "label": f"{event.type} → {event.strikes_after} Strike(s)",
                "customer": _link(event.customer_id),
                "reservation": _link(event.reservation_id),
                "customer_id": event.customer_id,
                "reservation_id": event.reservation_id,
                "type": event.type,
                "strikes_after": event.strikes_after,
                "fee_amount": money_to_airtable(event.fee_amount),
                "created_at": dt_to_airtable(event.created_at),
            },
        )

    def add_fee(self, fee: Fee):
        self._create(
            T.FEES,
            {
                "label": f"{fee.reason.value} · {fee.amount} €",
                "customer": _link(fee.customer_id),
                "reservation": _link(fee.reservation_id),
                "customer_id": fee.customer_id,
                "reservation_id": fee.reservation_id,
                "amount": money_to_airtable(fee.amount),
                "reason": fee.reason.value,
                "status": fee.status,
                "created_at": dt_to_airtable(self._now()),
            },
        )

    def list_fees_for_customer(self, customer_id):
        return [
            Fee(
                customer_id=_link_id(r["fields"], "customer_id", "customer"),
                reservation_id=_link_id(r["fields"], "reservation_id", "reservation"),
                amount=money_from_airtable(r["fields"].get("amount")),
                reason=ViolationType(r["fields"]["reason"]),
                status=r["fields"].get("status", "OPEN"),
            )
            for r in self._where(T.FEES, customer_id=customer_id)
        ]

    def add_event_log(self, entry: EventLogEntry):
        self._create(
            T.EVENT_LOG,
            {
                "event_type": entry.event_type,
                "source": entry.source,
                "reservation": _link(entry.reservation_id),
                "reservation_id": entry.reservation_id,
                "payload": json.dumps(entry.payload, default=str, ensure_ascii=False),
                "created_at": dt_to_airtable(entry.created_at or self._now()),
            },
        )
