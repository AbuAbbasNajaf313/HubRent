"""Verfügbarkeit von Geräten.

Ein Gerät ist belegt, wenn eine aktive Reservierung (PENDING, CONFIRMED, PICKED_UP)
zeitlich überlappt. Nach jedem Mietende gibt es einen Puffer (Rückgabe, Reinigung).

Analogie Werkstatt: Eine Hebebühne ist nicht nur während der Reparatur belegt,
sondern auch noch, während sie danach saubergemacht wird. Der Puffer gilt in
beide Richtungen: Eine neue Miete darf weder in den Puffer einer alten fallen,
noch darf ihr eigener Puffer in eine spätere Miete hineinragen.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from .models import Device, DeviceStatus, Reservation, ReservationStatus

BLOCKING_STATUSES = frozenset(
    {ReservationStatus.PENDING, ReservationStatus.CONFIRMED, ReservationStatus.PICKED_UP}
)


def overlaps(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime, buffer: timedelta
) -> bool:
    """True, wenn sich [a_start, a_end + buffer) und [b_start, b_end + buffer) schneiden."""
    return a_start < b_end + buffer and b_start < a_end + buffer


def is_device_free(
    device: Device,
    reservations: Iterable[Reservation],
    start: datetime,
    end: datetime,
    buffer: timedelta,
    ignore_reservation_id: str | None = None,
) -> bool:
    if device.status is not DeviceStatus.ACTIVE:
        return False
    for r in reservations:
        if r.device_id != device.id or r.status not in BLOCKING_STATUSES:
            continue
        if ignore_reservation_id and r.id == ignore_reservation_id:
            continue
        if overlaps(start, end, r.start_at, r.end_at, buffer):
            return False
    return True


def find_free_device(
    devices: Iterable[Device],
    reservations: Iterable[Reservation],
    device_type_id: str,
    hub_id: str,
    start: datetime,
    end: datetime,
    buffer: timedelta,
) -> Device | None:
    """Liefert das freie Gerät mit der kleinsten Fachnummer (deterministisch) oder None."""
    reservations = list(reservations)
    candidates = sorted(
        (d for d in devices if d.device_type_id == device_type_id and d.hub_id == hub_id),
        key=lambda d: d.locker_number,
    )
    for device in candidates:
        if is_device_free(device, reservations, start, end, buffer):
            return device
    return None


def count_free_devices(
    devices: Iterable[Device],
    reservations: Iterable[Reservation],
    device_type_id: str,
    hub_id: str,
    start: datetime,
    end: datetime,
    buffer: timedelta,
) -> int:
    reservations = list(reservations)
    return sum(
        1
        for d in devices
        if d.device_type_id == device_type_id
        and d.hub_id == hub_id
        and is_device_free(d, reservations, start, end, buffer)
    )
