"""Begrenzung von Fehlversuchen (z. B. PIN am Terminal).

Gleitendes Zeitfenster: Es zählen nur Fehlversuche der letzten ``window``.
Nach ``limit`` Fehlversuchen ist der Schlüssel gesperrt, bis der älteste Versuch
aus dem Fenster fällt. Erfolgreiche Versuche zählen nicht.

Warum? Eine 6-stellige PIN hat 1 Mio. Möglichkeiten. Mit 5 Versuchen pro Minute
bräuchte ein Angreifer im Schnitt über 69 Tage am Stück, statt Sekunden.

Gespeichert wird im Arbeitsspeicher. Das reicht für die Demo (ein gunicorn-Worker);
produktiv käme das z. B. in Redis, damit mehrere Server dieselben Zähler sehen.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta


class AttemptLimiter:
    def __init__(self, limit: int = 5, window: timedelta = timedelta(minutes=1)) -> None:
        self.limit = limit
        self.window = window
        self._failures: dict[str, deque[datetime]] = defaultdict(deque)

    def _prune(self, key: str, now: datetime) -> deque[datetime]:
        q = self._failures[key]
        while q and q[0] <= now - self.window:
            q.popleft()
        return q

    def retry_after(self, key: str, now: datetime) -> timedelta | None:
        """``None`` = erlaubt, sonst die Wartezeit bis zum nächsten Versuch."""
        q = self._prune(key, now)
        if len(q) < self.limit:
            return None
        return q[0] + self.window - now

    def record_failure(self, key: str, now: datetime) -> None:
        self._prune(key, now).append(now)

    def remaining(self, key: str, now: datetime) -> int:
        return max(0, self.limit - len(self._prune(key, now)))
