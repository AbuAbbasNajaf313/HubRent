"""Mietzeiträume und Preise.

| Mietart     | Zeitraum                              | Preis                 |
|-------------|---------------------------------------|-----------------------|
| FOUR_HOURS  | Start + 4 h                           | 0,8 × Tagesmiete      |
| DAY         | Start + n × 24 h (n = 1 … 14)          | n × Tagesmiete        |
| WEEKEND     | Fr 14:00 – Mo 10:00 (lokale Zeit)      | 1,5 × Tagesmiete      |

Wichtig: Das Wochenende wird in *lokaler* Zeit (Europe/Berlin) berechnet und erst
danach nach UTC umgerechnet. Sonst wäre es an Wochenenden mit Zeitumstellung eine
Stunde verschoben.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from .errors import InvalidBookingTime
from .models import RentalType
from .rule_config import RuleConfig

FOUR_HOURS_FACTOR = Decimal("0.8")
WEEKEND_FACTOR = Decimal("1.5")
WEEKEND_START = (4, time(14, 0))  # Freitag (weekday 4), 14:00
WEEKEND_END = (0, time(10, 0))    # Montag  (weekday 0), 10:00
CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    """Kaufmännisch auf Cent runden."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _require_aware(dt: datetime) -> None:
    if dt.tzinfo is None:
        raise ValueError("Zeitpunkte müssen zeitzonenbewusst sein (tz-aware).")


def is_weekend_start(start: datetime, rules: RuleConfig) -> bool:
    local = start.astimezone(rules.timezone)
    weekday, t = WEEKEND_START
    return local.weekday() == weekday and local.time() == t


def compute_end(rental_type: RentalType, start: datetime, rules: RuleConfig, days: int = 1) -> datetime:
    """Berechnet das Mietende (UTC) und prüft, ob Start/Dauer zur Mietart passen."""
    _require_aware(start)
    if rental_type is RentalType.FOUR_HOURS:
        return (start + timedelta(hours=4)).astimezone(timezone.utc)
    if rental_type is RentalType.DAY:
        if not 1 <= days <= rules.max_rental_days:
            raise InvalidBookingTime(f"Tagesmiete nur für 1 bis {rules.max_rental_days} Tage.")
        return (start + timedelta(days=days)).astimezone(timezone.utc)
    if rental_type is RentalType.WEEKEND:
        if not is_weekend_start(start, rules):
            raise InvalidBookingTime("Wochenendmiete startet immer freitags um 14:00 Uhr.")
        local_start = start.astimezone(rules.timezone)
        monday = local_start.date() + timedelta(days=3)
        local_end = datetime.combine(monday, WEEKEND_END[1], tzinfo=rules.timezone)
        return local_end.astimezone(timezone.utc)
    raise InvalidBookingTime(f"Unbekannte Mietart: {rental_type}")


def compute_price(rental_type: RentalType, daily_rate: Decimal, days: int = 1) -> Decimal:
    if rental_type is RentalType.FOUR_HOURS:
        return money(daily_rate * FOUR_HOURS_FACTOR)
    if rental_type is RentalType.DAY:
        return money(daily_rate * days)
    if rental_type is RentalType.WEEKEND:
        return money(daily_rate * WEEKEND_FACTOR)
    raise InvalidBookingTime(f"Unbekannte Mietart: {rental_type}")


def validate_start(start: datetime, now: datetime, rules: RuleConfig, rental_type: RentalType) -> None:
    """Prüft Vorlaufzeit, maximale Vorausbuchung und Startraster."""
    _require_aware(start)
    _require_aware(now)
    if start < now + rules.min_lead_time:
        raise InvalidBookingTime("Der Start liegt zu kurz in der Zukunft.")
    if start > now + rules.max_advance:
        raise InvalidBookingTime("So weit im Voraus kann nicht gebucht werden.")
    if rental_type is not RentalType.WEEKEND:
        granularity_s = int(rules.start_granularity.total_seconds())
        local = start.astimezone(rules.timezone)
        seconds_of_day = local.hour * 3600 + local.minute * 60 + local.second
        if local.microsecond or seconds_of_day % granularity_s:
            raise InvalidBookingTime("Startzeit muss auf einer vollen Stunde liegen.")


# --- Startvorschläge für die Oberfläche -------------------------------------------

def next_possible_start(now: datetime, rules: RuleConfig) -> datetime:
    """Frühester gültiger Start: ``now`` + Vorlauf, aufgerundet auf das Startraster (lokale Zeit)."""
    _require_aware(now)
    earliest = (now + rules.min_lead_time).astimezone(rules.timezone)
    step = int(rules.start_granularity.total_seconds())
    seconds = earliest.hour * 3600 + earliest.minute * 60 + earliest.second + (1 if earliest.microsecond else 0)
    rounded = -(-seconds // step) * step  # aufrunden auf ein Vielfaches des Rasters
    midnight = datetime.combine(earliest.date(), time(0), tzinfo=rules.timezone)
    # Rechnen mit gleicher tzinfo ist in Python Wanduhrzeit: 13:00 bleibt 13:00, auch bei Zeitumstellung.
    return midnight + timedelta(seconds=rounded)


def upcoming_weekend_starts(now: datetime, rules: RuleConfig, count: int = 8) -> list[datetime]:
    """Die nächsten buchbaren Freitage 14:00 (lokale Zeit), höchstens bis ``max_advance``."""
    _require_aware(now)
    local = now.astimezone(rules.timezone)
    weekday, t = WEEKEND_START
    friday = local.date() + timedelta(days=(weekday - local.weekday()) % 7)
    result: list[datetime] = []
    while len(result) < count:
        start = datetime.combine(friday, t, tzinfo=rules.timezone)
        if start > now + rules.max_advance:
            break
        if start >= now + rules.min_lead_time:
            result.append(start)
        friday += timedelta(days=7)
    return result
