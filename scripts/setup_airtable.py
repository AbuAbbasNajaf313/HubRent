"""Legt die HubRent-Tabellen in einer bestehenden Airtable-Base an.

Aufruf (im Projektordner):
    python -m scripts.setup_airtable            # zeigt den Plan und führt ihn aus
    python -m scripts.setup_airtable --dry-run  # zeigt nur, was passieren würde

Voraussetzungen in der .env:
    AIRTABLE_API_TOKEN  Personal Access Token mit den Scopes
                        data.records:read, data.records:write,
                        schema.bases:read, schema.bases:write
                        und Zugriff auf genau diese Base
    AIRTABLE_BASE_ID    beginnt mit "app…" (steht in der URL der Base)

Idempotent: Vorhandene Tabellen und Felder werden nie überschrieben oder gelöscht,
nur Fehlendes wird ergänzt. Das Skript kann also gefahrlos mehrfach laufen.
"""
from __future__ import annotations

import argparse
import os
import sys

from app.envfile import load_env_file
from app.repository.airtable_repo import make_retry
from app.repository.airtable_setup import TypeMismatch, apply_plan, describe, plan_schema, read_existing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="nur anzeigen, nichts ändern")
    args = parser.parse_args(argv)

    load_env_file()
    token, base_id = os.environ.get("AIRTABLE_API_TOKEN"), os.environ.get("AIRTABLE_BASE_ID")
    if not token or not base_id:
        print("Fehler: AIRTABLE_API_TOKEN und AIRTABLE_BASE_ID müssen in der .env stehen.", file=sys.stderr)
        return 2

    from pyairtable import Api

    base = Api(token, timeout=(5, 30), retry_strategy=make_retry()).base(base_id)
    print(f"Lese Schema der Base {base_id} …")
    actions = plan_schema(read_existing(base))

    if not actions:
        print("✓ Alles vorhanden, nichts zu tun.")
        return 0

    if args.dry_run:
        print("Geplante Änderungen (--dry-run, nichts ausgeführt):")
        for a in actions:
            print("  · " + describe(a))
        return 0

    print("Führe aus:")
    apply_plan(base, actions)
    mismatches = [a for a in actions if isinstance(a, TypeMismatch)]
    print("✓ Fertig." if not mismatches else f"Fertig, aber {len(mismatches)} Feld(er) bitte von Hand prüfen (siehe oben).")
    print(
        "\nHinweis: Airtable legt bei Verknüpfungen automatisch Gegenfelder an "
        "(z. B. 'Devices' in Hubs). Die sind gewollt und können bleiben."
    )
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
