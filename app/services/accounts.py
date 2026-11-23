"""Registrierung und Login.

Passwörter werden mit Werkzeug gehasht (scrypt, mit Salt). Gespeichert wird nur
der Hash; beim Login wird das eingegebene Passwort erneut gehasht und verglichen.
"""
from __future__ import annotations

import re
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from app.domain.errors import DomainError
from app.domain.models import Customer
from app.repository.base import Repository

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8


class AccountService:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def register(self, email: str, full_name: str, password: str, terms_accepted: bool, now: datetime) -> Customer:
        email = (email or "").strip().lower()
        full_name = (full_name or "").strip()
        if not EMAIL_RE.match(email):
            raise DomainError("Bitte gib eine gültige E-Mail-Adresse ein.")
        if not full_name:
            raise DomainError("Bitte gib deinen Namen ein.")
        if len(password or "") < MIN_PASSWORD_LENGTH:
            raise DomainError(f"Das Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen haben.")
        if not terms_accepted:
            raise DomainError("Bitte akzeptiere die AGB und die Fair-Use-Regeln.")
        if self.repo.get_customer_by_email(email):
            raise DomainError("Zu dieser E-Mail-Adresse gibt es bereits ein Konto.")
        return self.repo.add_customer(
            Customer(
                id="",
                email=email,
                full_name=full_name,
                password_hash=generate_password_hash(password),
                terms_accepted_at=now,
            )
        )

    def authenticate(self, email: str, password: str) -> Customer | None:
        customer = self.repo.get_customer_by_email((email or "").strip().lower())
        if customer and customer.password_hash and check_password_hash(customer.password_hash, password or ""):
            return customer
        return None
