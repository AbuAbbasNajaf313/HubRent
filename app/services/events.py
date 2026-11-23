"""Versand von Ereignissen an n8n.

Der Service ruft nur ``publisher.publish(event_type, payload)`` auf. Ob dahinter
ein HTTP-Webhook (n8n) oder eine Liste im Test steckt, ist ihm egal.
Ein fehlgeschlagener Versand darf die Nutzeraktion nie blockieren: Er wird
protokolliert, n8n bzw. ein Admin kann ihn später nachholen.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Protocol

log = logging.getLogger(__name__)


class EventPublisher(Protocol):
    def publish(self, event_type: str, payload: dict[str, Any]) -> bool: ...


class RecordingPublisher:
    """Für Tests: merkt sich alle Events."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def publish(self, event_type: str, payload: dict[str, Any]) -> bool:
        self.events.append((event_type, payload))
        return True

    def types(self) -> list[str]:
        return [t for t, _ in self.events]


class N8nWebhookPublisher:
    """Schickt Events per POST an den n8n-Webhook (WF-01 Mail Dispatcher)."""

    def __init__(self, url: str, secret: str, timeout: float = 3.0) -> None:
        self.url = url
        self.secret = secret
        self.timeout = timeout

    def publish(self, event_type: str, payload: dict[str, Any]) -> bool:
        body = json.dumps({"event": event_type, **payload}, default=str).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "X-HubRent-Secret": self.secret},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return 200 <= resp.status < 300
        except Exception as exc:  # Netzwerkfehler dürfen die App nicht stoppen
            log.warning("Event %s konnte nicht an n8n gesendet werden: %s", event_type, exc)
            return False
