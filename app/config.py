"""App-Konfiguration aus Umgebungsvariablen (.env).

``REPOSITORY`` entscheidet über die Datenquelle:
- ``memory``: Demo-Daten im Arbeitsspeicher, kein Airtable-Konto nötig.
  Daten gehen beim Neustart verloren.
- ``airtable``: echte Base (Token + Base-ID nötig).
Ohne Angabe wird ``airtable`` genutzt, sobald Token und Base-ID gesetzt sind.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from typing import Mapping

from app.domain.rule_config import RuleConfig


PLACEHOLDER_PREFIX = "bitte-"  # Platzhalter aus .env.example gelten als "nicht gesetzt"


def _secret(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    return "" if value.startswith(PLACEHOLDER_PREFIX) else value


@dataclass(frozen=True)
class AppConfig:
    secret_key: str
    public_base_url: str = "http://localhost:8000"
    repository: str = "memory"
    airtable_token: str = ""
    airtable_base_id: str = ""
    n8n_event_webhook_url: str = ""
    n8n_webhook_secret: str = ""
    internal_api_secret: str = ""
    admin_email: str = ""
    seed_email_base: str = ""
    rules: RuleConfig = field(default_factory=RuleConfig)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AppConfig":
        env = os.environ if env is None else env
        token = env.get("AIRTABLE_API_TOKEN", "").strip()
        base_id = env.get("AIRTABLE_BASE_ID", "").strip()
        repository = env.get("REPOSITORY", "").strip().lower() or ("airtable" if token and base_id else "memory")
        if repository not in {"memory", "airtable"}:
            raise ValueError("REPOSITORY muss 'memory' oder 'airtable' sein.")
        if repository == "airtable" and not (token and base_id):
            raise ValueError("REPOSITORY=airtable braucht AIRTABLE_API_TOKEN und AIRTABLE_BASE_ID.")
        return cls(
            # Ohne festen Schlüssel sind Logins nach jedem Neustart ungültig. Für die Demo okay.
            secret_key=_secret(env, "FLASK_SECRET_KEY") or secrets.token_hex(32),
            public_base_url=env.get("PUBLIC_BASE_URL", "http://localhost:8000").strip(),
            repository=repository,
            airtable_token=token,
            airtable_base_id=base_id,
            n8n_event_webhook_url=env.get("N8N_EVENT_WEBHOOK_URL", "").strip(),
            n8n_webhook_secret=_secret(env, "N8N_WEBHOOK_SECRET"),
            internal_api_secret=_secret(env, "INTERNAL_API_SECRET"),
            admin_email=env.get("ADMIN_EMAIL", "").strip(),
            seed_email_base=env.get("SEED_EMAIL_BASE", "").strip(),
            rules=RuleConfig.from_env(dict(env)),
        )
