"""Repository-Schnittstelle.

Die Services kennen nur diese abstrakte Klasse, nicht Airtable. Dadurch können
Tests ein ``InMemoryRepository`` einsetzen und später ließe sich Airtable z. B.
gegen PostgreSQL tauschen, ohne eine Zeile Geschäftslogik zu ändern.

Analogie: Eine genormte Werkzeugaufnahme (z. B. SDS-plus). Der Bohrhammer
(Service) funktioniert mit jedem Bohrer (Repository), der die Norm erfüllt.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.domain.models import Customer, Device, DeviceType, Hub, Reservation, ViolationType


@dataclass
class StrikeEvent:
    customer_id: str
    reservation_id: str | None
    type: str  # NO_SHOW | LATE_CANCEL | REDUCTION
    strikes_after: int
    fee_amount: Decimal
    created_at: datetime


@dataclass
class Fee:
    customer_id: str
    reservation_id: str
    amount: Decimal
    reason: ViolationType
    status: str = "OPEN"


@dataclass
class EventLogEntry:
    event_type: str
    source: str
    reservation_id: str | None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


class Repository(ABC):
    # Stammdaten
    @abstractmethod
    def get_hub(self, hub_id: str) -> Hub | None: ...

    @abstractmethod
    def list_hubs(self) -> list[Hub]: ...

    @abstractmethod
    def get_device_type(self, type_id: str) -> DeviceType | None: ...

    @abstractmethod
    def list_device_types(self) -> list[DeviceType]: ...

    @abstractmethod
    def get_device(self, device_id: str) -> Device | None: ...

    @abstractmethod
    def list_devices(self, device_type_id: str | None = None, hub_id: str | None = None) -> list[Device]: ...

    # Kunden
    @abstractmethod
    def get_customer(self, customer_id: str) -> Customer | None: ...

    @abstractmethod
    def get_customer_by_email(self, email: str) -> Customer | None: ...

    @abstractmethod
    def add_customer(self, customer: Customer) -> Customer: ...

    @abstractmethod
    def update_customer(self, customer: Customer) -> None: ...

    # Reservierungen
    @abstractmethod
    def get_reservation(self, reservation_id: str) -> Reservation | None: ...

    @abstractmethod
    def find_reservation_by_token_hash(self, token_hash: str) -> Reservation | None: ...

    @abstractmethod
    def find_reservation_by_code(self, code: str) -> Reservation | None: ...

    @abstractmethod
    def list_reservations_for_devices(self, device_ids: list[str]) -> list[Reservation]: ...

    @abstractmethod
    def list_reservations_for_customer(self, customer_id: str) -> list[Reservation]: ...

    @abstractmethod
    def add_reservation(self, reservation: Reservation) -> Reservation: ...

    @abstractmethod
    def update_reservation(self, reservation: Reservation) -> None: ...

    # Protokoll / Strikes / Gebühren
    @abstractmethod
    def add_strike_event(self, event: StrikeEvent) -> None: ...

    @abstractmethod
    def add_fee(self, fee: Fee) -> None: ...

    @abstractmethod
    def list_fees_for_customer(self, customer_id: str) -> list[Fee]: ...

    @abstractmethod
    def add_event_log(self, entry: EventLogEntry) -> None: ...
