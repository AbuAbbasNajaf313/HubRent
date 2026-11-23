from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.domain.models import (
    Device,
    DeviceStatus,
    RentalType,
    Reservation,
    ReservationStatus,
)
from app.domain.rule_config import RuleConfig

BERLIN = ZoneInfo("Europe/Berlin")


def berlin(y, mo, d, h=0, mi=0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=BERLIN)


@pytest.fixture
def rules() -> RuleConfig:
    return RuleConfig()


@pytest.fixture
def now() -> datetime:
    # Montag, 23.11.2026, 12:00 Berlin
    return berlin(2026, 11, 23, 12)


def make_reservation(
    *,
    id="r1",
    device_id="d1",
    start: datetime,
    hours: float = 24,
    status=ReservationStatus.PENDING,
    created_at: datetime | None = None,
    daily_rate=Decimal("20.00"),
) -> Reservation:
    return Reservation(
        id=id,
        customer_id="c1",
        device_id=device_id,
        rental_type=RentalType.DAY,
        start_at=start.astimezone(timezone.utc),
        end_at=(start + timedelta(hours=hours)).astimezone(timezone.utc),
        price=daily_rate,
        daily_rate_snapshot=daily_rate,
        status=status,
        created_at=(created_at or start - timedelta(days=7)).astimezone(timezone.utc),
    )


def make_device(id="d1", type_id="t1", hub_id="h1", locker=1, status=DeviceStatus.ACTIVE) -> Device:
    return Device(id=id, code=id.upper(), device_type_id=type_id, hub_id=hub_id, locker_number=locker, status=status)
