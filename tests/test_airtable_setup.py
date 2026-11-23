"""Setup-Plan (Meta API) und Seed-Logik, beides ohne Netzwerk getestet."""
from app.domain.models import ReservationStatus as S
from app.repository import airtable_schema as T
from app.repository.airtable_setup import AddField, AddLink, CreateTable, plan_schema, seed_airtable
from app.seed_data import build_seed

from .fake_airtable import FakeBase


def full_existing() -> dict[str, dict[str, str]]:
    existing = {}
    for table in T.TABLES:
        fields = {f.name: f.type for f in table.fields}
        fields.update({link.name: "multipleRecordLinks" for link in table.links})
        existing[table.name] = fields
    return existing


def test_empty_base_creates_all_tables_then_links():
    actions = plan_schema({})
    creates = [a for a in actions if isinstance(a, CreateTable)]
    assert [a.table.name for a in creates] == [t.name for t in T.TABLES]
    first_link = next(i for i, a in enumerate(actions) if isinstance(a, AddLink))
    assert all(isinstance(a, CreateTable) for a in actions[:first_link])  # Links brauchen Tabellen-IDs
    assert any(a.table == T.RESERVATIONS and a.link.name == "device" for a in actions if isinstance(a, AddLink))


def test_complete_base_needs_nothing():
    assert plan_schema(full_existing()) == []


def test_missing_field_is_added_and_nothing_overwritten():
    existing = full_existing()
    del existing[T.RESERVATIONS]["pin"]
    existing[T.HUBS]["my_own_column"] = "singleLineText"  # Fremdes Feld bleibt unangetastet
    actions = plan_schema(existing)
    assert len(actions) == 1 and isinstance(actions[0], AddField)
    assert (actions[0].table, actions[0].field.name) == (T.RESERVATIONS, "pin")


def test_primary_field_comes_first():
    primaries = {t.name: t.fields[0].name for t in T.TABLES}
    assert primaries[T.RESERVATIONS] == "reservation_code"
    assert primaries[T.CUSTOMERS] == "email"
    assert primaries[T.DEVICES] == "device_code"


def test_status_choices_match_domain_enum():
    status = next(f for f in T.table(T.RESERVATIONS).fields if f.name == "status")
    assert {c["name"] for c in status.options["choices"]} == {s.value for s in S}


def test_seed_is_idempotent():
    base = FakeBase()
    seed = build_seed(password_hasher=lambda p: "h")
    ids1 = seed_airtable(base, seed)
    ids2 = seed_airtable(base, seed)
    assert ids1 == ids2
    assert len(base(T.DEVICES).records) == len(seed.devices)
    assert len(base(T.CUSTOMERS).records) == 3


def test_seed_links_devices_to_hub_and_type():
    base = FakeBase()
    ids = seed_airtable(base, build_seed(password_hasher=lambda p: "h"))
    dev = base(T.DEVICES).records[ids["devices"]["TH-TA-01"]]
    assert dev["hub"] == [ids["hubs"]["hub-TH"]] and dev["hub_id"] == ids["hubs"]["hub-TH"]
    assert dev["device_type"] == [ids["device_types"]["type-TA"]]


def test_reset_clears_transaction_tables_only():
    base = FakeBase()
    seed = build_seed(password_hasher=lambda p: "h")
    seed_airtable(base, seed)
    base(T.RESERVATIONS).create({"reservation_code": "HR-OLD001"})
    base(T.EVENT_LOG).create({"event_type": "x"})
    seed_airtable(base, seed, reset=True)
    assert base(T.RESERVATIONS).records == {} and base(T.EVENT_LOG).records == {}
    assert len(base(T.HUBS).records) == 2


class FakeMetaBase:
    """Nachbau von pyairtable.Base für schema/create_table/create_field."""

    def __init__(self):
        self.tables: dict[str, dict] = {}  # name → {"id":…, "fields": {name: type}}
        self.calls: list[tuple] = []

    def schema(self, force=False):
        from types import SimpleNamespace as NS

        return NS(tables=[
            NS(id=t["id"], name=n, fields=[NS(name=f, type=ty) for f, ty in t["fields"].items()])
            for n, t in self.tables.items()
        ])

    def create_table(self, name, fields):
        self.calls.append(("create_table", name))
        self.tables[name] = {"id": f"tbl{name}", "fields": {f["name"]: f["type"] for f in fields}}

    def table(self, name):
        base = self

        class _T:
            def create_field(self, fname, ftype, options=None):
                base.calls.append(("create_field", name, fname, (options or {}).get("linkedTableId")))
                base.tables[name]["fields"][fname] = ftype

        return _T()


def test_apply_plan_builds_full_schema_and_second_run_is_noop():
    from app.repository.airtable_setup import apply_plan, read_existing

    base = FakeMetaBase()
    apply_plan(base, plan_schema(read_existing(base)), log=lambda _: None)
    assert ("create_field", T.RESERVATIONS, "device", "tblDevices") in base.calls
    assert plan_schema(read_existing(base)) == []
