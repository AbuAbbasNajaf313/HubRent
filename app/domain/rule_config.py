"""Regel-Parameter (Fristen, Fenster, Puffer) als eine unveränderliche Konfiguration.

Im DEMO_MODE werden alle Fristen durch 60 geteilt: aus 48 h werden 48 min,
aus 30 min werden 30 s. Die Mietdauern selbst (4 h, Tag, Wochenende) bleiben echt.
So lässt sich der komplette Ablauf im Demo-Video in wenigen Minuten zeigen.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class RuleConfig:
    reminder_before: timedelta = timedelta(hours=48)
    confirm_deadline_before: timedelta = timedelta(hours=24)
    late_cancel_before: timedelta = timedelta(hours=24)
    pickup_window_before: timedelta = timedelta(minutes=30)
    pickup_window_after: timedelta = timedelta(minutes=120)
    return_grace: timedelta = timedelta(minutes=15)
    cancel_grace_after_booking: timedelta = timedelta(minutes=15)
    buffer_after_rental: timedelta = timedelta(minutes=30)
    min_lead_time: timedelta = timedelta(minutes=30)
    max_advance: timedelta = timedelta(days=60)
    start_granularity: timedelta = timedelta(hours=1)
    clean_rentals_for_reduction: int = 5
    max_rental_days: int = 14
    timezone: ZoneInfo = ZoneInfo("Europe/Berlin")
    demo_mode: bool = False

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "RuleConfig":
        env = dict(os.environ if env is None else env)
        demo = env.get("DEMO_MODE", "false").lower() in {"1", "true", "yes"}
        scale = 60 if demo else 1

        def hours(key: str, default: float) -> timedelta:
            return timedelta(hours=float(env.get(key, default))) / scale

        def minutes(key: str, default: float) -> timedelta:
            return timedelta(minutes=float(env.get(key, default))) / scale

        return cls(
            reminder_before=hours("REMINDER_HOURS_BEFORE", 48),
            confirm_deadline_before=hours("CONFIRM_DEADLINE_HOURS_BEFORE", 24),
            late_cancel_before=hours("LATE_CANCEL_HOURS_BEFORE", 24),
            pickup_window_before=minutes("PICKUP_WINDOW_BEFORE_MIN", 30),
            pickup_window_after=minutes("PICKUP_WINDOW_AFTER_MIN", 120),
            return_grace=minutes("RETURN_GRACE_MIN", 15),
            cancel_grace_after_booking=minutes("CANCEL_GRACE_AFTER_BOOKING_MIN", 15),
            buffer_after_rental=minutes("BUFFER_AFTER_RENTAL_MIN", 30),
            min_lead_time=minutes("MIN_LEAD_TIME_MIN", 30),
            start_granularity=timedelta(minutes=1) if demo else timedelta(hours=1),
            clean_rentals_for_reduction=int(env.get("CLEAN_RENTALS_FOR_STRIKE_REDUCTION", 5)),
            timezone=ZoneInfo(env.get("APP_TIMEZONE", "Europe/Berlin")),
            demo_mode=demo,
        )
