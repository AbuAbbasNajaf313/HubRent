"""In-Memory-Repository für Tests und lokale Entwicklung ohne Airtable."""
from __future__ import annotations

import copy
import itertools

from app.domain.models import Customer, Device, DeviceType, Hub, Reservation

from .base import EventLogEntry, Fee, Repository, StrikeEvent


class InMemoryRepository(Repository):
    def __init__(self) -> None:
        self.hubs: dict[str, Hub] = {}
        self.device_types: dict[str, DeviceType] = {}
        self.devices: dict[str, Device] = {}
        self.customers: dict[str, Customer] = {}
        self.reservations: dict[str, Reservation] = {}
        self.strike_events: list[StrikeEvent] = []
        self.fees: list[Fee] = []
        self.event_log: list[EventLogEntry] = []
        self._ids = itertools.count(1)

    def _next_id(self, prefix: str) -> str:
        return f"{prefix}{next(self._ids)}"

    # Kopien zurückgeben, damit sich das Verhalten wie bei einer echten DB anfühlt:
    # Änderungen wirken erst nach update_*().
    def get_hub(self, hub_id):
        return copy.deepcopy(self.hubs.get(hub_id))

    def list_hubs(self):
        return [copy.deepcopy(h) for h in self.hubs.values()]

    def get_device_type(self, type_id):
        return copy.deepcopy(self.device_types.get(type_id))

    def list_device_types(self):
        return [copy.deepcopy(t) for t in self.device_types.values()]

    def get_device(self, device_id):
        return copy.deepcopy(self.devices.get(device_id))

    def list_devices(self, device_type_id=None, hub_id=None):
        return [
            copy.deepcopy(d)
            for d in self.devices.values()
            if (device_type_id is None or d.device_type_id == device_type_id)
            and (hub_id is None or d.hub_id == hub_id)
        ]

    def get_customer(self, customer_id):
        return copy.deepcopy(self.customers.get(customer_id))

    def get_customer_by_email(self, email):
        email = email.strip().lower()
        return next((copy.deepcopy(c) for c in self.customers.values() if c.email == email), None)

    def add_customer(self, customer):
        customer = copy.deepcopy(customer)
        customer.id = customer.id or self._next_id("cus")
        customer.email = customer.email.strip().lower()
        self.customers[customer.id] = customer
        return copy.deepcopy(customer)

    def update_customer(self, customer):
        self.customers[customer.id] = copy.deepcopy(customer)

    def get_reservation(self, reservation_id):
        return copy.deepcopy(self.reservations.get(reservation_id))

    def find_reservation_by_token_hash(self, token_hash):
        return next(
            (copy.deepcopy(r) for r in self.reservations.values() if r.token_hash == token_hash), None
        )

    def list_reservations_for_devices(self, device_ids):
        ids = set(device_ids)
        return [copy.deepcopy(r) for r in self.reservations.values() if r.device_id in ids]

    def list_reservations_for_customer(self, customer_id):
        return sorted(
            (copy.deepcopy(r) for r in self.reservations.values() if r.customer_id == customer_id),
            key=lambda r: r.start_at,
            reverse=True,
        )

    def add_reservation(self, reservation):
        reservation = copy.deepcopy(reservation)
        reservation.id = reservation.id or self._next_id("res")
        self.reservations[reservation.id] = reservation
        return copy.deepcopy(reservation)

    def update_reservation(self, reservation):
        self.reservations[reservation.id] = copy.deepcopy(reservation)

    def add_strike_event(self, event):
        self.strike_events.append(copy.deepcopy(event))

    def add_fee(self, fee):
        self.fees.append(copy.deepcopy(fee))

    def list_fees_for_customer(self, customer_id):
        return [copy.deepcopy(f) for f in self.fees if f.customer_id == customer_id]

    def add_event_log(self, entry):
        self.event_log.append(copy.deepcopy(entry))
