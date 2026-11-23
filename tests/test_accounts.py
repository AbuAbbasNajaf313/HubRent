"""Registrierung und Login (AccountService)."""
import pytest

from app.domain.errors import DomainError
from app.repository.memory_repo import InMemoryRepository
from app.services.accounts import AccountService

from .conftest import berlin

NOW = berlin(2026, 11, 23, 12)


@pytest.fixture
def svc():
    return AccountService(InMemoryRepository())


def test_register_and_login(svc):
    c = svc.register(" Kim@Example.com ", "Kim Test", "geheim123", terms_accepted=True, now=NOW)
    assert c.email == "kim@example.com" and c.terms_accepted_at == NOW
    assert c.password_hash and "geheim123" not in c.password_hash
    assert svc.authenticate("KIM@example.com", "geheim123").id == c.id


def test_wrong_password_or_unknown_email(svc):
    svc.register("kim@example.com", "Kim", "geheim123", terms_accepted=True, now=NOW)
    assert svc.authenticate("kim@example.com", "falsch123") is None
    assert svc.authenticate("niemand@example.com", "geheim123") is None


def test_duplicate_email_rejected(svc):
    svc.register("kim@example.com", "Kim", "geheim123", terms_accepted=True, now=NOW)
    with pytest.raises(DomainError, match="bereits"):
        svc.register("KIM@example.com", "Kim 2", "geheim123", terms_accepted=True, now=NOW)


@pytest.mark.parametrize(
    "email, name, pw, terms, msg",
    [
        ("kein-at", "Kim", "geheim123", True, "E-Mail"),
        ("kim@example.com", " ", "geheim123", True, "Name"),
        ("kim@example.com", "Kim", "kurz", True, "8 Zeichen"),
        ("kim@example.com", "Kim", "geheim123", False, "AGB"),
    ],
)
def test_validation(svc, email, name, pw, terms, msg):
    with pytest.raises(DomainError, match=msg):
        svc.register(email, name, pw, terms_accepted=terms, now=NOW)
