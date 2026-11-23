"""Logik hinter ``scripts/setup_airtable.py`` und ``scripts/seed.py``.

Getrennt von den Skripten, damit sie ohne Netzwerk testbar ist:

1. ``plan_schema`` vergleicht das gewünschte Schema mit dem, was in der Base schon
   existiert, und liefert eine Liste von Aktionen. Was schon da ist, wird nie
   verändert oder gelöscht → das Setup ist **idempotent** (beliebig oft ausführbar).
2. ``apply_plan`` führt die Aktionen über die Airtable Meta API aus.
3. ``seed_airtable`` schreibt die Demo-Daten per Upsert (Schlüssel = Primärfeld),
   ist also ebenfalls wiederholbar, ohne Duplikate zu erzeugen.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable

from app.seed_data import Seed

from . import airtable_schema as T
from .airtable_repo import customer_fields, device_fields, device_type_fields, dt_to_airtable, hub_fields


@dataclass(frozen=True)
class CreateTable:
    table: T.TableSpec


@dataclass(frozen=True)
class AddField:
    table: str
    field: T.FieldSpec


@dataclass(frozen=True)
class AddLink:
    table: str
    link: T.LinkSpec


@dataclass(frozen=True)
class TypeMismatch:
    table: str
    field: str
    expected: str
    actual: str


Action = CreateTable | AddField | AddLink | TypeMismatch


def plan_schema(existing: dict[str, dict[str, str]]) -> list[Action]:
    """``existing``: Tabellenname → {Feldname: Feldtyp} aus der Base.

    Reihenfolge: erst alle Tabellen, dann fehlende Felder, zuletzt Verknüpfungen,
    denn ein Link-Feld braucht die ID der Zieltabelle.
    """
    tables: list[Action] = []
    fields: list[Action] = []
    links: list[Action] = []
    for spec in T.TABLES:
        have = existing.get(spec.name)
        if have is None:
            tables.append(CreateTable(spec))
            have = {f.name: f.type for f in spec.fields}
        for f in spec.fields:
            if f.name not in have:
                fields.append(AddField(spec.name, f))
            elif have[f.name] != f.type:
                fields.append(TypeMismatch(spec.name, f.name, f.type, have[f.name]))
        for link in spec.links:
            if link.name not in have:
                links.append(AddLink(spec.name, link))
            elif have[link.name] != "multipleRecordLinks":
                fields.append(TypeMismatch(spec.name, link.name, "multipleRecordLinks", have[link.name]))
    return tables + fields + links


def describe(action: Action) -> str:
    if isinstance(action, CreateTable):
        return f"Tabelle anlegen: {action.table.name}"
    if isinstance(action, AddField):
        return f"Feld anlegen: {action.table}.{action.field.name} ({action.field.type})"
    if isinstance(action, AddLink):
        return f"Verknüpfung anlegen: {action.table}.{action.link.name} → {action.link.target}"
    return (
        f"ACHTUNG {action.table}.{action.field}: Typ ist '{action.actual}', erwartet '{action.expected}'. "
        "Bitte in Airtable von Hand anpassen."
    )


def read_existing(base: Any) -> dict[str, dict[str, str]]:
    """Liest das Schema einer pyairtable-``Base``."""
    schema = base.schema(force=True)
    return {t.name: {f.name: f.type for f in t.fields} for t in schema.tables}


def apply_plan(base: Any, actions: list[Action], log: Callable[[str], None] = print) -> None:
    for action in actions:
        log("  · " + describe(action))
        if isinstance(action, CreateTable):
            base.create_table(action.table.name, [f.to_api() for f in action.table.fields])
        elif isinstance(action, AddField):
            f = action.field
            base.table(action.table).create_field(f.name, f.type, options=f.options)
    link_actions = [a for a in actions if isinstance(a, AddLink)]
    if link_actions:
        ids = {t.name: t.id for t in base.schema(force=True).tables}
        for a in link_actions:
            base.table(a.table).create_field(
                a.link.name, "multipleRecordLinks", options={"linkedTableId": ids[a.link.target]}
            )


# --- Seed ------------------------------------------------------------------------------

TRANSACTION_TABLES = [T.EVENT_LOG, T.FEES, T.STRIKE_EVENTS, T.RESERVATIONS]


def _upsert(table: Any, rows: list[tuple[str, dict[str, Any]]], key_field: str) -> dict[str, str]:
    """Upsert in 10er-Blöcken (Airtable-Limit). Liefert Seed-Schlüssel → Record-ID."""
    ids: dict[str, str] = {}
    for i in range(0, len(rows), 10):
        chunk = rows[i : i + 10]
        result = table.batch_upsert([{"fields": f} for _, f in chunk], key_fields=[key_field])
        by_key = {r["fields"][key_field]: r["id"] for r in result["records"]}
        for seed_key, fields in chunk:
            ids[seed_key] = by_key[fields[key_field]]
    return ids


def seed_airtable(tables: Callable[[str], Any], seed: Seed, reset: bool = False) -> dict[str, dict[str, str]]:
    """Schreibt Hubs, Gerätetypen, Geräte und Demo-Kunden.

    ``reset=True`` löscht vorher alle Reservierungen, Strikes, Gebühren und das
    EventLog. Praktisch vor einer Demo-Aufnahme. Stammdaten bleiben erhalten,
    Demo-Kunden werden auf ihren Ausgangs-Strike-Stand zurückgesetzt.
    """
    if reset:
        for name in TRANSACTION_TABLES:
            table = tables(name)
            table.batch_delete([r["id"] for r in table.all()])

    hub_ids = _upsert(tables(T.HUBS), [(h.id, hub_fields(h)) for h in seed.hubs], "name")
    type_ids = _upsert(
        tables(T.DEVICE_TYPES), [(t.id, device_type_fields(t)) for t in seed.device_types], "name"
    )

    device_rows = []
    for d in seed.devices:
        linked = replace(d, device_type_id=type_ids[d.device_type_id], hub_id=hub_ids[d.hub_id])
        device_rows.append((d.id, device_fields(linked)))
    device_ids = _upsert(tables(T.DEVICES), device_rows, "device_code")

    customer_rows = [
        (c.id, {**customer_fields(c), "created_at": dt_to_airtable(c.terms_accepted_at)}) for c in seed.customers
    ]
    customer_ids = _upsert(tables(T.CUSTOMERS), customer_rows, "email")
    return {"hubs": hub_ids, "device_types": type_ids, "devices": device_ids, "customers": customer_ids}
