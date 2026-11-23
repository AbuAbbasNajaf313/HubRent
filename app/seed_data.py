"""Fiktive Demo-Daten (Spezifikation Abschnitt 6).

Die Daten werden als Domain-Objekte beschrieben, nicht als Airtable-Datensätze.
Dadurch nutzen sie sowohl ``scripts/seed.py`` (Airtable) als auch die lokale
Entwicklung mit dem ``InMemoryRepository``. Die IDs hier sind stabile
Schlüssel (z. B. ``hub-NK``); Airtable vergibt beim Anlegen eigene Record-IDs.

Alle Namen, Adressen und Preise sind ausgedacht. Es werden keine realen
Vermieter oder Baumarktketten nachgebildet.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from app.domain.models import Customer, Device, DeviceStatus, DeviceType, Hub

DEMO_PASSWORD = "hubrent-demo"
DEMO_EMAIL_DOMAIN = "hubrent-demo.example"  # .example ist reserviert, Mails gehen nirgendwohin
TERMS_ACCEPTED_AT = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)

_HUBS = [
    # key, name, address, store_name
    ("NK", "Hub Neukölln", "Karl-Marx-Straße 100, 12043 Berlin", "Baumarkt Karl-Marx-Straße (fiktiv)"),
    ("TH", "Hub Tempelhof", "Tempelhofer Damm 150, 12099 Berlin", "Baumarkt Tempelhofer Damm (fiktiv)"),
]

_DEVICE_TYPES = [
    # key, name, category, daily_rate, description
    ("BH", "Akku-Bohrhammer", "Bohren", "20.00", "18 V, SDS-plus, für Beton und Mauerwerk. Inkl. Bohrerset."),
    ("SS", "Stichsäge", "Sägen", "15.00", "Pendelhub-Stichsäge für Holz, Metall und Kunststoff."),
    ("TR", "Teppichreiniger", "Reinigen", "30.00", "Sprühextraktionsgerät für Teppiche und Polster."),
    ("FS", "Fliesenschneider", "Renovieren", "25.00", "Manueller Fliesenschneider bis 60 cm Schnittlänge."),
    ("TA", "Tapetenablöser", "Renovieren", "25.00", "Dampf-Tapetenablöser mit großer Dampfplatte."),
    ("HD", "Hochdruckreiniger", "Reinigen", "35.00", "150 bar, mit Flächenreiniger für Terrasse und Einfahrt."),
    ("VT", "Vertikutierer", "Garten", "40.00", "Elektro-Vertikutierer, 38 cm Arbeitsbreite."),
    ("PS", "Parkettschleifmaschine", "Schleifen", "110.00", "Walzenschleifmaschine für Parkett und Dielen."),
]

# hub_key, type_key, Anzahl Geräte; das erste Gerät aus _MAINTENANCE ist in Wartung
_DEVICES = [
    ("NK", "BH", 2), ("TH", "BH", 1),
    ("NK", "SS", 1), ("TH", "SS", 1),
    ("NK", "TR", 1), ("TH", "TR", 1),
    ("NK", "FS", 1),
    ("TH", "TA", 1),
    ("NK", "HD", 1), ("TH", "HD", 1),
    ("NK", "VT", 1), ("TH", "VT", 1),
    ("NK", "PS", 1), ("TH", "PS", 1),
]
_MAINTENANCE = {"NK-PS-01"}

_CUSTOMERS = [
    # alias, full_name, strikes, clean_streak
    ("lena", "Lena Demo", 0, 0),
    ("jonas", "Jonas Demo", 1, 3),
    ("mira", "Mira Demo", 3, 0),
]


@dataclass
class Seed:
    hubs: list[Hub]
    device_types: list[DeviceType]
    devices: list[Device]
    customers: list[Customer]


def demo_email(alias: str, email_base: str | None) -> str:
    """Ohne Basisadresse: ``alias@hubrent-demo.example``.

    Mit Basisadresse (z. B. dein Gmail) wird Plus-Adressierung genutzt:
    ``max@gmail.com`` → ``max+lena@gmail.com``. So landen alle Demo-Mails in
    deinem Postfach, obwohl es drei verschiedene Kunden sind.
    """
    if not email_base:
        return f"{alias}@{DEMO_EMAIL_DOMAIN}"
    local, _, domain = email_base.strip().lower().partition("@")
    return f"{local}+{alias}@{domain}"


def _default_hasher(password: str) -> str:
    from werkzeug.security import generate_password_hash

    return generate_password_hash(password)


def build_seed(
    email_base: str | None = None,
    password_hasher: Callable[[str], str] = _default_hasher,
) -> Seed:
    hubs = [Hub(f"hub-{k}", name, addr, store) for k, name, addr, store in _HUBS]
    types = [
        DeviceType(f"type-{k}", name, cat, Decimal(rate), description=desc)
        for k, name, cat, rate, desc in _DEVICE_TYPES
    ]

    devices: list[Device] = []
    next_locker: dict[str, int] = {}
    for hub_key, type_key, count in _DEVICES:
        for n in range(1, count + 1):
            locker = next_locker.get(hub_key, 1)
            next_locker[hub_key] = locker + 1
            code = f"{hub_key}-{type_key}-{n:02d}"
            devices.append(
                Device(
                    id=code,
                    code=code,
                    device_type_id=f"type-{type_key}",
                    hub_id=f"hub-{hub_key}",
                    locker_number=locker,
                    status=DeviceStatus.MAINTENANCE if code in _MAINTENANCE else DeviceStatus.ACTIVE,
                )
            )

    password_hash = password_hasher(DEMO_PASSWORD)  # einmal hashen reicht, scrypt ist langsam
    customers = [
        Customer(
            id=f"cus-{alias}",
            email=demo_email(alias, email_base),
            full_name=name,
            password_hash=password_hash,
            strikes=strikes,
            clean_streak=streak,
            terms_accepted_at=TERMS_ACCEPTED_AT,
        )
        for alias, name, strikes, streak in _CUSTOMERS
    ]
    return Seed(hubs, types, devices, customers)


def load_into_memory(repo, seed: Seed) -> None:
    """Füllt ein ``InMemoryRepository`` (lokale Entwicklung ohne Airtable)."""
    for h in seed.hubs:
        repo.hubs[h.id] = h
    for t in seed.device_types:
        repo.device_types[t.id] = t
    for d in seed.devices:
        repo.devices[d.id] = d
    for c in seed.customers:
        repo.add_customer(c)
