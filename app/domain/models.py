"""Domain-Modelle von HubRent.

Reine Datenklassen ohne I/O. Geldbeträge sind immer ``Decimal`` (nie float),
damit z. B. 0,1 + 0,2 nicht 0,30000000000000004 ergibt.
Alle Zeitpunkte sind zeitzonenbewusst und werden in UTC gespeichert.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class RentalType(str, Enum):
    FOUR_HOURS = "FOUR_HOURS"
    DAY = "DAY"
    WEEKEND = "WEEKEND"


class ReservationStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    PICKED_UP = "PICKED_UP"
    RETURNED = "RETURNED"
    CANCELLED_BY_CUSTOMER = "CANCELLED_BY_CUSTOMER"
    CANCELLED_AUTO = "CANCELLED_AUTO"
    NO_SHOW = "NO_SHOW"


class DeviceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"


class ViolationType(str, Enum):
    NO_SHOW = "NO_SHOW"
    LATE_CANCEL = "LATE_CANCEL"


@dataclass
class Hub:
    id: str
    name: str
    address: str
    store_name: str = ""
    active: bool = True


@dataclass
class DeviceType:
    id: str
    name: str
    category: str
    daily_rate: Decimal
    description: str = ""
    image_url: str = ""


@dataclass
class Device:
    id: str
    code: str
    device_type_id: str
    hub_id: str
    locker_number: int
    status: DeviceStatus = DeviceStatus.ACTIVE


@dataclass
class Customer:
    id: str
    email: str
    full_name: str
    password_hash: str = ""
    strikes: int = 0
    clean_streak: int = 0
    terms_accepted_at: datetime | None = None


@dataclass
class Reservation:
    id: str
    customer_id: str
    device_id: str
    rental_type: RentalType
    start_at: datetime
    end_at: datetime
    price: Decimal
    daily_rate_snapshot: Decimal
    status: ReservationStatus
    created_at: datetime
    token_hash: str = ""
    token_expires_at: datetime | None = None
    pin: str = ""
    reminder_sent_at: datetime | None = None
    confirmed_at: datetime | None = None
    cancelled_at: datetime | None = None
    picked_up_at: datetime | None = None
    returned_at: datetime | None = None
