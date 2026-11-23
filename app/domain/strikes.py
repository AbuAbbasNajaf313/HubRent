"""Strike-System.

| Strike-Stand nach Verstoß | Gebühr                      |
|---------------------------|-----------------------------|
| 1                         | 0 € (Verwarnung)            |
| 2                         | 50 % einer Tagesmiete       |
| ≥ 3                       | 75 % einer Tagesmiete       |

Abbau: 5 pünktliche, unproblematische Mieten am Stück → 1 Strike weniger.
Jeder Verstoß und jede verspätete Rückgabe setzt die Serie auf 0.
Ohne Strikes wird keine Serie "angespart".

Analogie: wie ein Wartungsintervall. Nach 5 störungsfreien Zyklen wird ein
Warnzähler zurückgesetzt, eine Störung startet die Zählung neu.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .models import ViolationType
from .pricing import money

FEE_RATE_SECOND_STRIKE = Decimal("0.50")
FEE_RATE_THIRD_PLUS = Decimal("0.75")


@dataclass(frozen=True)
class ViolationResult:
    violation: ViolationType
    strikes_after: int
    clean_streak_after: int
    fee: Decimal


@dataclass(frozen=True)
class CleanRentalResult:
    strikes_after: int
    clean_streak_after: int
    strike_reduced: bool


def calculate_fee(strikes_after_violation: int, daily_rate: Decimal) -> Decimal:
    if strikes_after_violation <= 1:
        return Decimal("0.00")
    rate = FEE_RATE_SECOND_STRIKE if strikes_after_violation == 2 else FEE_RATE_THIRD_PLUS
    return money(daily_rate * rate)


def register_violation(strikes: int, violation: ViolationType, daily_rate: Decimal) -> ViolationResult:
    new_strikes = strikes + 1
    return ViolationResult(
        violation=violation,
        strikes_after=new_strikes,
        clean_streak_after=0,
        fee=calculate_fee(new_strikes, daily_rate),
    )


def register_return(strikes: int, clean_streak: int, on_time: bool, required: int = 5) -> CleanRentalResult:
    if not on_time:
        return CleanRentalResult(strikes, 0, False)
    if strikes == 0:
        return CleanRentalResult(0, 0, False)
    streak = clean_streak + 1
    if streak >= required:
        return CleanRentalResult(strikes - 1, 0, True)
    return CleanRentalResult(strikes, streak, False)


def progress_text(strikes: int, clean_streak: int, required: int = 5) -> str:
    """Kurzer Text für Konto-Seite und Mails."""
    if strikes == 0:
        return "Keine Strikes – alles im grünen Bereich."
    return f"{strikes} Strike(s) · {clean_streak}/{required} saubere Mieten bis zum Abbau"
