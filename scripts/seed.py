"""Schreibt fiktive Demo-Daten in die Airtable-Base.

Aufruf (im Projektordner, nach scripts.setup_airtable):
    python -m scripts.seed           # Hubs, Gerätetypen, Geräte, 3 Demo-Kunden
    python -m scripts.seed --reset   # vorher alle Reservierungen, Strikes,
                                     # Gebühren und das EventLog löschen

Wiederholbar: Datensätze werden über ihr Primärfeld (Name, Gerätecode, E-Mail)
aktualisiert statt doppelt angelegt.

Demo-Kunden (Passwort für alle: siehe DEMO_PASSWORD in app/seed_data.py):
    lena  – 0 Strikes
    jonas – 1 Strike, 3/5 saubere Mieten
    mira  – 3 Strikes
Mit SEED_EMAIL_BASE=du@gmail.com in der .env bekommen sie Adressen wie
du+lena@gmail.com, sodass alle Demo-Mails in deinem Postfach ankommen.
"""
from __future__ import annotations

import argparse
import os
import sys

from app.envfile import load_env_file
from app.repository import airtable_schema as T
from app.repository.airtable_repo import make_retry
from app.repository.airtable_setup import TRANSACTION_TABLES, seed_airtable
from app.seed_data import DEMO_PASSWORD, build_seed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help=f"Tabellen {', '.join(TRANSACTION_TABLES)} leeren")
    args = parser.parse_args(argv)

    load_env_file()
    token, base_id = os.environ.get("AIRTABLE_API_TOKEN"), os.environ.get("AIRTABLE_BASE_ID")
    if not token or not base_id:
        print("Fehler: AIRTABLE_API_TOKEN und AIRTABLE_BASE_ID müssen in der .env stehen.", file=sys.stderr)
        return 2

    from pyairtable import Api

    api = Api(token, timeout=(5, 30), retry_strategy=make_retry())
    seed = build_seed(email_base=os.environ.get("SEED_EMAIL_BASE") or None)
    if args.reset:
        print("Lösche Reservierungen, Strikes, Gebühren und EventLog …")
    ids = seed_airtable(lambda name: api.table(base_id, name), seed, reset=args.reset)

    print(f"✓ {len(ids['hubs'])} Hubs, {len(ids['device_types'])} Gerätetypen, {len(ids['devices'])} Geräte")
    print(f"✓ {len(ids['customers'])} Demo-Kunden (Passwort: {DEMO_PASSWORD}):")
    for c in seed.customers:
        print(f"    {c.email:<40} {c.strikes} Strike(s), Serie {c.clean_streak}/5")
    hub_ids = ", ".join(f"{h.name} = {ids['hubs'][h.id]}" for h in seed.hubs)
    print(f"Terminal-URLs nutzen die Hub-IDs: {hub_ids}")
    print(f"Tabelle {T.DEVICES}: NK-PS-01 steht absichtlich auf MAINTENANCE.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
