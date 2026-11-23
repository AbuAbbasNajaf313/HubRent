"""Anwendungsfälle rund um eine Miete.

Der RentalService verbindet Domain-Regeln, Repository und Event-Versand.
Er ist die *einzige* Stelle, an der Reservierungen ihren Status ändern,
egal ob der Auslöser ein Kunde (Flask-UI), das Terminal oder n8n (interne API) ist.

Idempotenz: Die n8n-Aufrufe (send_reminder, auto_cancel, mark_no_show) dürfen
beliebig oft kommen. Ist nichts (mehr) zu tun, wird ``changed=False`` geliefert
und nichts verändert. Wichtig, weil Cron-Jobs und Retries doppelt feuern können.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.domain import rules as R
from app.domain.availability import BLOCKING_STATUSES, count_free_devices, find_free_device, is_device_free
from app.domain.errors import DomainError, InvalidBookingTime, NotAvailable, NotFound
from app.domain.models import (
    Customer,
    DeviceType,
    RentalType,
    Reservation,
    ReservationStatus as S,
    ViolationType,
)
from app.domain.pricing import compute_end, compute_price, next_possible_start, validate_start
from app.domain.rule_config import RuleConfig
from app.domain.strikes import progress_text, register_return, register_violation
from app.repository.base import EventLogEntry, Fee, Repository, StrikeEvent

from .events import EventPublisher
from .tokens import hash_token, new_pin, new_reservation_code, new_token


@dataclass(frozen=True)
class Quote:
    price: Decimal
    start_at: datetime
    end_at: datetime
    free_devices: int
    binding: bool  # True = kurzfristig, sofort verbindlich


@dataclass
class Result:
    changed: bool
    reservation: Reservation | None
    customer: Customer | None = None
    token: str | None = None  # Klartext nur für Links in Mails
    fee: Decimal = Decimal("0.00")
    message: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CatalogEntry:
    device_type: DeviceType
    prices: dict[RentalType, Decimal]
    free_by_hub: dict[str, int]  # Hub-ID → freie Geräte für 4 h ab dem nächsten möglichen Start

    @property
    def free_total(self) -> int:
        return sum(self.free_by_hub.values())


@dataclass(frozen=True)
class AccountItem:
    reservation: Reservation
    details: dict[str, Any]
    cancellation: R.CancellationAssessment
    can_confirm: bool


@dataclass(frozen=True)
class AccountOverview:
    customer: Customer
    active: list[AccountItem]
    past: list[AccountItem]
    open_fees: Decimal
    required_clean_rentals: int


class RentalService:
    def __init__(
        self,
        repo: Repository,
        rules: RuleConfig,
        publisher: EventPublisher,
        public_base_url: str = "http://localhost:8000",
    ) -> None:
        self.repo = repo
        self.rules = rules
        self.publisher = publisher
        self.base_url = public_base_url.rstrip("/")

    # ------------------------------------------------------------------ Angebot
    def quote(
        self,
        device_type_id: str,
        hub_id: str,
        rental_type: RentalType,
        start: datetime,
        now: datetime,
        days: int = 1,
    ) -> Quote:
        device_type = self.repo.get_device_type(device_type_id)
        if device_type is None:
            raise DomainError("Unbekannter Gerätetyp.")
        validate_start(start, now, self.rules, rental_type)
        end = compute_end(rental_type, start, self.rules, days)
        start_utc = start.astimezone(timezone.utc)
        devices = self.repo.list_devices(device_type_id, hub_id)
        reservations = self.repo.list_reservations_for_devices([d.id for d in devices])
        free = count_free_devices(
            devices, reservations, device_type_id, hub_id, start_utc, end, self.rules.buffer_after_rental
        )
        return Quote(
            price=compute_price(rental_type, device_type.daily_rate, days),
            start_at=start_utc,
            end_at=end,
            free_devices=free,
            binding=R.initial_status(start_utc, now, self.rules) is S.CONFIRMED,
        )

    # ------------------------------------------------------------------ Katalog
    def catalog(self, now: datetime, hub_id: str | None = None, category: str | None = None) -> list[CatalogEntry]:
        """Alle Gerätetypen mit Preisen und "jetzt frei"-Zahl pro Hub.

        "Jetzt frei" = für eine 4-h-Miete ab dem nächsten möglichen Start verfügbar.
        Nur zwei Abfragen für alle Geräte und Reservierungen, nicht eine pro Typ
        (wichtig für das Airtable-Rate-Limit).
        """
        hubs = [h for h in self.repo.list_hubs() if h.active and (hub_id is None or h.id == hub_id)]
        types = [t for t in self.repo.list_device_types() if category is None or t.category == category]
        devices = self.repo.list_devices()
        reservations = self.repo.list_reservations_for_devices([d.id for d in devices])
        start = next_possible_start(now, self.rules).astimezone(timezone.utc)
        end = compute_end(RentalType.FOUR_HOURS, start, self.rules)
        buffer = self.rules.buffer_after_rental
        return [
            CatalogEntry(
                device_type=t,
                prices={rt: compute_price(rt, t.daily_rate) for rt in RentalType},
                free_by_hub={
                    h.id: count_free_devices(devices, reservations, t.id, h.id, start, end, buffer) for h in hubs
                },
            )
            for t in sorted(types, key=lambda t: (t.category, t.name))
        ]

    # ------------------------------------------------------------------ Konto
    def account_overview(self, customer_id: str, now: datetime) -> AccountOverview:
        customer = self._customer(customer_id)
        active, past = [], []
        for r in self.repo.list_reservations_for_customer(customer_id):
            item = AccountItem(
                reservation=r,
                details=self._payload(r, customer),
                cancellation=R.assess_cancellation(r, now, self.rules),
                can_confirm=R.can_confirm(r, now, self.rules),
            )
            (active if r.status in BLOCKING_STATUSES else past).append(item)
        active.sort(key=lambda i: i.reservation.start_at)
        open_fees = sum((f.amount for f in self.repo.list_fees_for_customer(customer_id) if f.status == "OPEN"), Decimal("0.00"))
        return AccountOverview(customer, active, past, open_fees, self.rules.clean_rentals_for_reduction)

    def reservation_for_token(self, token: str, now: datetime) -> Reservation:
        """Für die Token-Seiten: Reservierung anzeigen, ohne etwas zu ändern."""
        return self._by_token(token, now)

    def details(self, r: Reservation, token: str | None = None) -> dict[str, Any]:
        """Alles, was eine Seite oder Mail über eine Reservierung anzeigt (mit Token auch die Links)."""
        return self._payload(r, self._customer(r.customer_id), token=token)

    # ------------------------------------------------------------------ Buchen
    def book(
        self,
        customer_id: str,
        device_type_id: str,
        hub_id: str,
        rental_type: RentalType,
        start: datetime,
        now: datetime,
        days: int = 1,
        binding_accepted: bool = False,
    ) -> Result:
        customer = self._customer(customer_id)
        device_type = self.repo.get_device_type(device_type_id)
        if device_type is None:
            raise DomainError("Unbekannter Gerätetyp.")
        q = self.quote(device_type_id, hub_id, rental_type, start, now, days)
        if q.binding and not binding_accepted:
            raise InvalidBookingTime("Kurzfristige Buchungen sind sofort verbindlich, bitte bestätigen.")

        devices = self.repo.list_devices(device_type_id, hub_id)
        reservations = self.repo.list_reservations_for_devices([d.id for d in devices])
        device = find_free_device(
            devices, reservations, device_type_id, hub_id, q.start_at, q.end_at, self.rules.buffer_after_rental
        )
        if device is None:
            raise NotAvailable("Für diesen Zeitraum ist an diesem Hub kein Gerät frei.")

        token, token_hash = new_token()
        status = R.initial_status(q.start_at, now, self.rules)
        reservation = Reservation(
            id="",
            code=new_reservation_code(),
            customer_id=customer.id,
            device_id=device.id,
            rental_type=rental_type,
            start_at=q.start_at,
            end_at=q.end_at,
            price=q.price,
            daily_rate_snapshot=device_type.daily_rate,
            status=status,
            created_at=now.astimezone(timezone.utc),
            token_hash=token_hash,
            token_expires_at=q.start_at,
        )
        if status is S.CONFIRMED:
            reservation.confirmed_at = reservation.created_at
            reservation.pin = self._unique_pin(hub_id)
        reservation = self.repo.add_reservation(reservation)

        # Nachkontrolle gegen gleichzeitige Buchungen (Airtable kennt keine Transaktionen)
        others = self.repo.list_reservations_for_devices([device.id])
        if not is_device_free(
            device, others, q.start_at, q.end_at, self.rules.buffer_after_rental, ignore_reservation_id=reservation.id
        ):
            reservation.status = S.CANCELLED_AUTO
            reservation.cancelled_at = now
            self.repo.update_reservation(reservation)
            raise NotAvailable("Das Gerät wurde gerade von jemand anderem gebucht. Bitte erneut versuchen.")

        event = "reservation.confirmed" if status is S.CONFIRMED else "reservation.created"
        self._emit(event, reservation, customer, token=token)
        return Result(True, reservation, customer, token=token)

    # ------------------------------------------------------------------ Kunde
    def confirm(self, token: str, now: datetime) -> Result:
        return self._confirm(self._by_token(token, now), now, token=token)

    def confirm_by_customer(self, reservation_id: str, customer_id: str, now: datetime) -> Result:
        """Bestätigen aus "Mein Konto" (eingeloggt, ohne Mail-Link)."""
        r = self._reservation(reservation_id)
        if r.customer_id != customer_id:
            raise DomainError("Diese Reservierung gehört nicht zu deinem Konto.")
        return self._confirm(r, now)

    def _confirm(self, r: Reservation, now: datetime, token: str | None = None) -> Result:
        customer = self._customer(r.customer_id)
        if r.status is S.CONFIRMED:
            return Result(False, r, customer, message="Bereits bestätigt.")
        if not R.can_confirm(r, now, self.rules):
            raise DomainError("Die Bestätigungsfrist ist abgelaufen.")
        R.transition(r, S.CONFIRMED)
        r.confirmed_at = now
        r.pin = self._unique_pin(self._hub_id_of(r))
        self.repo.update_reservation(r)
        self._emit("reservation.confirmed", r, customer, token=token)
        return Result(True, r, customer, token=token)

    def assess_cancellation(self, token: str, now: datetime) -> R.CancellationAssessment:
        return R.assess_cancellation(self._by_token(token, now), now, self.rules)

    def cancel(self, token: str, now: datetime) -> Result:
        r = self._by_token(token, now)
        return self._cancel(r, now)

    def cancel_by_customer(self, reservation_id: str, customer_id: str, now: datetime) -> Result:
        r = self._reservation(reservation_id)
        if r.customer_id != customer_id:
            raise DomainError("Diese Reservierung gehört nicht zu deinem Konto.")
        return self._cancel(r, now)

    def _cancel(self, r: Reservation, now: datetime) -> Result:
        customer = self._customer(r.customer_id)
        assessment = R.assess_cancellation(r, now, self.rules)
        if not assessment.allowed:
            raise DomainError(assessment.reason)
        R.transition(r, S.CANCELLED_BY_CUSTOMER)
        r.cancelled_at = now
        self.repo.update_reservation(r)
        fee = Decimal("0.00")
        if not assessment.free_of_charge:
            customer, fee = self._apply_violation(customer, r, ViolationType.LATE_CANCEL, now)
        self._emit("reservation.cancelled", r, customer, extra={"free_of_charge": assessment.free_of_charge, "fee": fee})
        return Result(True, r, customer, fee=fee, message=assessment.reason, extra={"free_of_charge": assessment.free_of_charge})

    # ------------------------------------------------------------------ n8n (idempotent)
    def send_reminder(self, reservation_id: str, now: datetime) -> Result:
        r = self._reservation(reservation_id)
        customer = self._customer(r.customer_id)
        if not R.reminder_due(r, now, self.rules):
            return Result(False, r, customer, message="Keine Erinnerung fällig.")
        token, token_hash = new_token()  # neuer Token, da der alte nur als Hash existiert
        r.token_hash = token_hash
        r.token_expires_at = r.start_at
        r.reminder_sent_at = now
        self.repo.update_reservation(r)
        payload = self._payload(r, customer, token=token)
        self._log("reminder.prepared", "n8n", r, {})
        return Result(True, r, customer, token=token, extra={"mail": payload})

    def auto_cancel(self, reservation_id: str, now: datetime) -> Result:
        r = self._reservation(reservation_id)
        customer = self._customer(r.customer_id)
        if not R.auto_cancel_due(r, now, self.rules):
            return Result(False, r, customer, message="Kein Auto-Storno fällig.")
        R.transition(r, S.CANCELLED_AUTO)
        r.cancelled_at = now
        self.repo.update_reservation(r)
        self._log("reservation.auto_cancelled", "n8n", r, {})
        return Result(True, r, customer, extra={"mail": self._payload(r, customer)})

    def mark_no_show(self, reservation_id: str, now: datetime) -> Result:
        r = self._reservation(reservation_id)
        customer = self._customer(r.customer_id)
        if not R.no_show_due(r, now, self.rules):
            return Result(False, r, customer, message="Kein No-Show fällig.")
        R.transition(r, S.NO_SHOW)
        self.repo.update_reservation(r)
        customer, fee = self._apply_violation(customer, r, ViolationType.NO_SHOW, now)
        self._log("reservation.no_show", "n8n", r, {"fee": str(fee)})
        payload = self._payload(r, customer, extra={"fee": fee})
        return Result(True, r, customer, fee=fee, extra={"mail": payload})

    # ------------------------------------------------------------------ Terminal
    def pick_up(self, hub_id: str, pin: str, now: datetime) -> Result:
        devices = {d.id: d for d in self.repo.list_devices(hub_id=hub_id)}
        candidates = [
            r
            for r in self.repo.list_reservations_for_devices(list(devices))
            if r.status is S.CONFIRMED and r.pin == pin
        ]
        r = next((c for c in candidates if R.can_pick_up(c, now, self.rules)), None)
        if r is None:
            raise DomainError("PIN ungültig oder außerhalb des Abholfensters.")
        R.transition(r, S.PICKED_UP)
        r.picked_up_at = now
        self.repo.update_reservation(r)
        customer = self._customer(r.customer_id)
        self._emit("reservation.picked_up", r, customer)
        return Result(True, r, customer, extra={"locker_number": devices[r.device_id].locker_number})

    def return_item(self, reservation_id: str, now: datetime) -> Result:
        r = self._reservation(reservation_id)
        R.transition(r, S.RETURNED)
        r.returned_at = now
        self.repo.update_reservation(r)
        customer = self._customer(r.customer_id)
        on_time = R.is_on_time_return(r, now, self.rules)
        res = register_return(customer.strikes, customer.clean_streak, on_time, self.rules.clean_rentals_for_reduction)
        customer.strikes, customer.clean_streak = res.strikes_after, res.clean_streak_after
        self.repo.update_customer(customer)
        if res.strike_reduced:
            self.repo.add_strike_event(
                StrikeEvent(customer.id, r.id, "REDUCTION", customer.strikes, Decimal("0.00"), now)
            )
            self._emit("strike.reduced", r, customer)
        self._emit("reservation.returned", r, customer, extra={"on_time": on_time})
        return Result(True, r, customer, extra={"on_time": on_time, "strike_reduced": res.strike_reduced})

    def return_at_hub(self, hub_id: str, code: str, now: datetime) -> Result:
        """Rückgabe am Terminal: Kunde tippt den Reservierungscode, das richtige Fach öffnet sich."""
        r = self.repo.find_reservation_by_code(code or "")
        if r is None:
            raise DomainError("Unbekannter Reservierungscode.")
        device = self.repo.get_device(r.device_id)
        if device is None or device.hub_id != hub_id:
            hub = self.repo.get_hub(device.hub_id) if device else None
            raise DomainError(f"Dieses Gerät gehört in den {hub.name if hub else 'anderen Hub'}.")
        if r.status is S.RETURNED:
            raise DomainError("Dieses Gerät wurde bereits zurückgegeben.")
        if r.status is not S.PICKED_UP:
            raise DomainError("Zu diesem Code wurde noch nichts abgeholt.")
        result = self.return_item(r.id, now)
        result.extra["locker_number"] = device.locker_number
        return result

    # ------------------------------------------------------------------ Hilfen
    def _apply_violation(
        self, customer: Customer, r: Reservation, violation: ViolationType, now: datetime
    ) -> tuple[Customer, Decimal]:
        v = register_violation(customer.strikes, violation, r.daily_rate_snapshot)
        customer.strikes, customer.clean_streak = v.strikes_after, v.clean_streak_after
        self.repo.update_customer(customer)
        self.repo.add_strike_event(StrikeEvent(customer.id, r.id, violation.value, v.strikes_after, v.fee, now))
        if v.fee > 0:
            self.repo.add_fee(Fee(customer.id, r.id, v.fee, violation))
        self._emit("strike.issued", r, customer, extra={"violation": violation.value, "fee": v.fee})
        return customer, v.fee

    def _by_token(self, token: str, now: datetime) -> Reservation:
        r = self.repo.find_reservation_by_token_hash(hash_token(token or ""))
        if r is None:
            raise DomainError("Dieser Link ist ungültig.")
        if r.token_expires_at and now > r.token_expires_at:
            raise DomainError("Dieser Link ist abgelaufen.")
        return r

    def _reservation(self, reservation_id: str) -> Reservation:
        r = self.repo.get_reservation(reservation_id)
        if r is None:
            raise NotFound("Reservierung nicht gefunden.")
        return r

    def _customer(self, customer_id: str) -> Customer:
        c = self.repo.get_customer(customer_id)
        if c is None:
            raise NotFound("Kunde nicht gefunden.")
        return c

    def _hub_id_of(self, r: Reservation) -> str:
        device = self.repo.get_device(r.device_id)
        return device.hub_id if device else ""

    def _unique_pin(self, hub_id: str) -> str:
        """PIN, die an diesem Hub gerade keine andere bestätigte Reservierung nutzt."""
        device_ids = [d.id for d in self.repo.list_devices(hub_id=hub_id)]
        used = {r.pin for r in self.repo.list_reservations_for_devices(device_ids) if r.status is S.CONFIRMED}
        for _ in range(50):
            pin = new_pin()
            if pin not in used:
                return pin
        raise DomainError("Konnte keine freie PIN erzeugen.")

    def _payload(
        self, r: Reservation, customer: Customer, token: str | None = None, extra: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        device = self.repo.get_device(r.device_id)
        device_type = self.repo.get_device_type(device.device_type_id) if device else None
        hub = self.repo.get_hub(device.hub_id) if device else None
        tz = self.rules.timezone
        fmt = "%d.%m.%Y, %H:%M Uhr"
        payload: dict[str, Any] = {
            "reservation": {
                "id": r.id,
                "code": r.code,
                "status": r.status.value,
                "rental_type": r.rental_type.value,
                "start_at": r.start_at.isoformat(),
                "end_at": r.end_at.isoformat(),
                "start_local": r.start_at.astimezone(tz).strftime(fmt),
                "end_local": r.end_at.astimezone(tz).strftime(fmt),
                "price": str(r.price),
                "pin": r.pin if r.status is S.CONFIRMED else "",
                "pickup_from_local": R.pickup_window(r, self.rules)[0].astimezone(tz).strftime(fmt),
                "pickup_until_local": R.pickup_window(r, self.rules)[1].astimezone(tz).strftime(fmt),
            },
            "customer": {
                "email": customer.email,
                "full_name": customer.full_name,
                "strikes": customer.strikes,
                "clean_streak": customer.clean_streak,
                "strike_text": progress_text(customer.strikes, customer.clean_streak, self.rules.clean_rentals_for_reduction),
            },
            "device": {
                "name": device_type.name if device_type else "",
                "locker_number": device.locker_number if device else None,
            },
            "hub": {"name": hub.name if hub else "", "address": hub.address if hub else ""},
        }
        if token:
            payload["links"] = {
                "confirm": f"{self.base_url}/r/{token}/bestaetigen",
                "cancel": f"{self.base_url}/r/{token}/stornieren",
            }
        if extra:
            payload["extra"] = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in extra.items()}
        return payload

    def _emit(
        self, event_type: str, r: Reservation, customer: Customer, token: str | None = None, extra: dict[str, Any] | None = None
    ) -> None:
        payload = self._payload(r, customer, token=token, extra=extra)
        ok = self.publisher.publish(event_type, payload)
        self._log(event_type, "flask", r, {"delivered": ok})

    def _log(self, event_type: str, source: str, r: Reservation, payload: dict[str, Any]) -> None:
        self.repo.add_event_log(EventLogEntry(event_type, source, r.id, payload))
