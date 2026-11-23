"""Sichere Links und PINs.

Gespeichert wird nur der SHA-256-Hash eines Tokens, nie der Klartext.
Wird die Datenbank geleakt, kann damit niemand Reservierungen bestätigen.
Analogie: Der Schlüsseldienst bewahrt einen Abdruck auf, nicht den Schlüssel selbst.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets


def new_token() -> tuple[str, str]:
    """Gibt (klartext_token, token_hash) zurück. Der Klartext geht nur in die Mail."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token(token: str, stored_hash: str) -> bool:
    if not token or not stored_hash:
        return False
    return hmac.compare_digest(hash_token(token), stored_hash)


# Ohne leicht verwechselbare Zeichen (0/O, 1/I/L), weil Kunden den Code am Terminal abtippen.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def new_reservation_code(length: int = 6) -> str:
    """Zufälliger, gut lesbarer Code wie ``HR-7K3QXM`` (31^6 ≈ 887 Mio. Möglichkeiten)."""
    return "HR-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def new_pin(length: int = 6) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))
