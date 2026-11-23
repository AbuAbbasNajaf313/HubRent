"""Application Factory: ``create_app()`` baut die Flask-App zusammen.

Alles, was die App von außen braucht (Konfiguration, Repository, Event-Versand,
Uhr), kann übergeben werden. Tests nutzen das, um eine feste Uhrzeit und ein
In-Memory-Repository einzusetzen. Ohne Argumente kommt alles aus der ``.env``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from flask import Flask

from app.config import AppConfig
from app.envfile import load_env_file
from app.repository.base import Repository
from app.services.accounts import AccountService
from app.services.attempts import AttemptLimiter
from app.services.events import EventPublisher, LoggingPublisher, N8nWebhookPublisher
from app.services.rentals import RentalService

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class HubRent:
    """Alles, was die Web-Schicht braucht, an einer Stelle (``app.extensions['hubrent']``)."""

    def __init__(self, config: AppConfig, repo: Repository, publisher: EventPublisher, clock: Clock) -> None:
        self.config = config
        self.repo = repo
        self.clock = clock
        self.rentals = RentalService(repo, config.rules, publisher, config.public_base_url)
        self.accounts = AccountService(repo)
        self.terminal_limiter = AttemptLimiter(limit=5)  # PIN-Fehlversuche pro Terminal und Minute


def _build_repo(config: AppConfig) -> Repository:
    if config.repository == "airtable":
        from app.repository.airtable_repo import AirtableRepository
        from app.repository.cached_repo import CachedRepository

        # Cache spart Airtable-Aufrufe (Rate-Limit, 1.000 Aufrufe/Monat im Gratis-Tarif)
        return CachedRepository(AirtableRepository.from_credentials(config.airtable_token, config.airtable_base_id))

    from app.repository.memory_repo import InMemoryRepository
    from app.seed_data import build_seed, load_into_memory

    repo = InMemoryRepository()
    load_into_memory(repo, build_seed(email_base=config.seed_email_base or None))
    return repo


def _build_publisher(config: AppConfig) -> EventPublisher:
    if config.n8n_event_webhook_url:
        return N8nWebhookPublisher(config.n8n_event_webhook_url, config.n8n_webhook_secret)
    return LoggingPublisher()


def create_app(
    config: AppConfig | None = None,
    *,
    repo: Repository | None = None,
    publisher: EventPublisher | None = None,
    clock: Clock = utc_now,
) -> Flask:
    if config is None:
        load_env_file()
        config = AppConfig.from_env()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=config.secret_key,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        WTF_CSRF_TIME_LIMIT=None,  # Token gilt so lange wie die Sitzung
    )
    app.extensions["hubrent"] = HubRent(
        config,
        repo if repo is not None else _build_repo(config),
        publisher if publisher is not None else _build_publisher(config),
        clock,
    )

    from app.web import init_web

    init_web(app)
    app.logger.info("HubRent gestartet (Daten: %s, Demo-Modus: %s)", config.repository, config.rules.demo_mode)
    return app
