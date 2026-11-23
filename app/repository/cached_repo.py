"""Cache vor dem eigentlichen Repository, um Airtable-Aufrufe zu sparen.

Airtable erlaubt 5 Requests/s und im Gratis-Tarif 1.000 Aufrufe pro Monat.
Ohne Cache kostet z. B. jede Katalogseite 4 Aufrufe und jeder Seitenaufruf eines
eingeloggten Kunden einen weiteren (Flask-Login lädt den Kunden).

Was gecacht wird und warum:
- **Stammdaten** (Hubs, Gerätetypen, Geräte): ändern sich praktisch nie, TTL 5 min.
  Alle Geräte werden auf einmal geladen und lokal gefiltert.
- **Kunden** (``get_customer``): kurze TTL. Änderungen über *diese* App (Strike,
  Abbau) aktualisieren den Cache sofort (Write-through).
- **Reservierungen, Gebühren, Protokoll**: nie. Verfügbarkeit muss immer stimmen.

Entwurfsmuster: *Decorator*. Die Klasse erfüllt dieselbe ``Repository``-Schnittstelle
und reicht alles Nicht-Gecachte durch. Services merken davon nichts.
Grenze: Wer direkt in Airtable etwas ändert, sieht es in der App erst nach Ablauf der TTL.
"""
from __future__ import annotations

import copy
import time
from typing import Any, Callable

from app.domain.models import Customer

from .base import Repository


class _Entry:
    __slots__ = ("value", "expires")

    def __init__(self, value: Any, expires: float) -> None:
        self.value = value
        self.expires = expires


class CachedRepository(Repository):
    def __init__(
        self,
        inner: Repository,
        ttl_seconds: float = 300,
        customer_ttl_seconds: float = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.inner = inner
        self.ttl = ttl_seconds
        self.customer_ttl = customer_ttl_seconds
        self.clock = clock
        self._cache: dict[str, _Entry] = {}

    # --- Hilfen ---------------------------------------------------------------------
    def _cached(self, key: str, loader: Callable[[], Any], ttl: float) -> Any:
        entry = self._cache.get(key)
        if entry is None or entry.expires <= self.clock():
            entry = _Entry(loader(), self.clock() + ttl)
            self._cache[key] = entry
        return copy.deepcopy(entry.value)  # Aufrufer dürfen ihre Kopie verändern

    def _put(self, key: str, value: Any, ttl: float) -> None:
        self._cache[key] = _Entry(copy.deepcopy(value), self.clock() + ttl)

    def invalidate(self) -> None:
        self._cache.clear()

    # --- Stammdaten (gecacht) -------------------------------------------------------
    def list_hubs(self):
        return self._cached("hubs", self.inner.list_hubs, self.ttl)

    def get_hub(self, hub_id):
        return next((h for h in self.list_hubs() if h.id == hub_id), None)

    def list_device_types(self):
        return self._cached("types", self.inner.list_device_types, self.ttl)

    def get_device_type(self, type_id):
        return next((t for t in self.list_device_types() if t.id == type_id), None)

    def list_devices(self, device_type_id=None, hub_id=None):
        devices = self._cached("devices", self.inner.list_devices, self.ttl)
        return [
            d
            for d in devices
            if (device_type_id is None or d.device_type_id == device_type_id) and (hub_id is None or d.hub_id == hub_id)
        ]

    def get_device(self, device_id):
        return next((d for d in self.list_devices() if d.id == device_id), None)

    # --- Kunden (kurz gecacht, Write-through) ----------------------------------------
    def get_customer(self, customer_id):
        return self._cached(f"customer:{customer_id}", lambda: self.inner.get_customer(customer_id), self.customer_ttl)

    def get_customer_by_email(self, email):
        customer = self.inner.get_customer_by_email(email)  # Login: immer frisch
        if customer:
            self._put(f"customer:{customer.id}", customer, self.customer_ttl)
        return customer

    def add_customer(self, customer: Customer):
        added = self.inner.add_customer(customer)
        self._put(f"customer:{added.id}", added, self.customer_ttl)
        return added

    def update_customer(self, customer: Customer):
        self.inner.update_customer(customer)
        self._put(f"customer:{customer.id}", customer, self.customer_ttl)

    # --- Durchgereicht (nie gecacht) --------------------------------------------------
    def get_reservation(self, reservation_id):
        return self.inner.get_reservation(reservation_id)

    def find_reservation_by_token_hash(self, token_hash):
        return self.inner.find_reservation_by_token_hash(token_hash)

    def find_reservation_by_code(self, code):
        return self.inner.find_reservation_by_code(code)

    def list_reservations_for_devices(self, device_ids):
        return self.inner.list_reservations_for_devices(device_ids)

    def list_reservations_for_customer(self, customer_id):
        return self.inner.list_reservations_for_customer(customer_id)

    def add_reservation(self, reservation):
        return self.inner.add_reservation(reservation)

    def update_reservation(self, reservation):
        self.inner.update_reservation(reservation)

    def add_strike_event(self, event):
        self.inner.add_strike_event(event)

    def add_fee(self, fee):
        self.inner.add_fee(fee)

    def list_fees_for_customer(self, customer_id):
        return self.inner.list_fees_for_customer(customer_id)

    def add_event_log(self, entry):
        self.inner.add_event_log(entry)
