"""Nachbau der wenigen pyairtable-Table-Methoden, die HubRent nutzt.

Verhält sich in den Punkten wie Airtable, die für das Mapping zählen:
- leere Felder (None, "", [], False) fehlen in der Antwort ganz,
- Währungen kommen als float zurück,
- Formeln: nur ``{feld}='wert'``-Vergleiche, verknüpft per AND(...) oder OR(...).
"""
from __future__ import annotations

import itertools
import re
from typing import Any

import requests

_EQ = re.compile(r"\{([^}]+)\}='((?:[^'\\]|\\.)*)'")
_ids = itertools.count(1)


class FakeHTTPError(requests.HTTPError):
    def __init__(self, status_code: int):
        response = requests.Response()
        response.status_code = status_code
        super().__init__(f"HTTP {status_code}", response=response)


def _clean(fields: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in fields.items():
        if v is None or v == "" or v == [] or v is False:
            continue
        out[k] = float(v) if hasattr(v, "as_tuple") else v  # Decimal → float wie die echte API
    return out


class FakeTable:
    def __init__(self, name: str) -> None:
        self.name = name
        self.records: dict[str, dict[str, Any]] = {}
        self.formulas: list[str] = []

    def _match(self, formula: Any, fields: dict[str, Any]) -> bool:
        if formula is None:
            return True
        text = str(formula)
        checks = [(f, v.replace("\\'", "'")) for f, v in _EQ.findall(text)]
        results = [str(fields.get(f, "")) == v for f, v in checks]
        return any(results) if text.startswith("OR(") else all(results)

    def all(self, formula=None, **_: Any) -> list[dict[str, Any]]:
        if formula is not None:
            self.formulas.append(str(formula))
        return [
            {"id": rid, "fields": dict(f)} for rid, f in self.records.items() if self._match(formula, f)
        ]

    def first(self, formula=None, **kw: Any):
        found = self.all(formula=formula, **kw)
        return found[0] if found else None

    def get(self, record_id: str) -> dict[str, Any]:
        if record_id not in self.records:
            raise FakeHTTPError(404)
        return {"id": record_id, "fields": dict(self.records[record_id])}

    def create(self, fields: dict[str, Any]) -> dict[str, Any]:
        rid = f"rec{next(_ids):014d}"
        self.records[rid] = _clean(fields)
        return self.get(rid)

    def update(self, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        current = self.records[record_id]
        for k, v in fields.items():
            current.pop(k, None)
        current.update(_clean(fields))
        return self.get(record_id)

    def batch_upsert(self, records, key_fields, **_: Any) -> dict[str, Any]:
        out, created, updated = [], [], []
        for rec in records:
            fields = rec["fields"]
            key = {k: fields[k] for k in key_fields}
            existing = next(
                (rid for rid, f in self.records.items() if all(f.get(k) == v for k, v in key.items())), None
            )
            if existing:
                out.append(self.update(existing, fields))
                updated.append(existing)
            else:
                r = self.create(fields)
                out.append(r)
                created.append(r["id"])
        return {"records": out, "createdRecords": created, "updatedRecords": updated}

    def batch_delete(self, record_ids) -> list[dict[str, Any]]:
        for rid in list(record_ids):
            self.records.pop(rid, None)
        return []


class FakeBase:
    """Liefert pro Tabellenname immer dieselbe FakeTable."""

    def __init__(self) -> None:
        self.tables: dict[str, FakeTable] = {}

    def __call__(self, name: str) -> FakeTable:
        return self.tables.setdefault(name, FakeTable(name))
