"""Fachliche Fehler. Die Web-Schicht übersetzt sie in verständliche Meldungen."""


class DomainError(Exception):
    """Basisklasse für alle Regelverletzungen."""


class NotFound(DomainError):
    """Reservierung, Kunde o. Ä. existiert nicht."""


class InvalidTransition(DomainError):
    """Ein Statuswechsel ist laut Statusmaschine nicht erlaubt."""


class InvalidBookingTime(DomainError):
    """Startzeit/Dauer passt nicht zu den Buchungsregeln."""


class NotAvailable(DomainError):
    """Kein freies Gerät für Typ, Hub und Zeitraum."""
