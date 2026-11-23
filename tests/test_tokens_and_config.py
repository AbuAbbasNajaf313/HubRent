from datetime import timedelta

from app.domain.rule_config import RuleConfig
from app.services.tokens import hash_token, new_pin, new_token, verify_token


def test_token_roundtrip():
    token, token_hash = new_token()
    assert token != token_hash
    assert verify_token(token, token_hash)
    assert not verify_token(token + "x", token_hash)
    assert not verify_token("", token_hash)
    assert hash_token(token) == token_hash


def test_tokens_are_unique():
    assert len({new_token()[0] for _ in range(100)}) == 100


def test_pin_format():
    pin = new_pin()
    assert len(pin) == 6 and pin.isdigit()


def test_config_defaults():
    c = RuleConfig.from_env({})
    assert c.reminder_before == timedelta(hours=48)
    assert c.pickup_window_after == timedelta(hours=2)
    assert not c.demo_mode


def test_config_demo_mode_scales_by_60():
    c = RuleConfig.from_env({"DEMO_MODE": "true"})
    assert c.reminder_before == timedelta(minutes=48)
    assert c.confirm_deadline_before == timedelta(minutes=24)
    assert c.pickup_window_after == timedelta(minutes=2)
    assert c.start_granularity == timedelta(minutes=1)


def test_reservation_code_format():
    from app.services.tokens import CODE_ALPHABET, new_reservation_code

    code = new_reservation_code()
    assert code.startswith("HR-") and len(code) == 9
    assert set(code[3:]) <= set(CODE_ALPHABET)
    assert not set("01ILO") & set(CODE_ALPHABET)


def test_placeholder_secrets_count_as_unset():
    from app.config import AppConfig

    cfg = AppConfig.from_env({"INTERNAL_API_SECRET": "bitte-zufallswert-eintragen", "N8N_WEBHOOK_SECRET": "echt123"})
    assert cfg.internal_api_secret == "" and cfg.n8n_webhook_secret == "echt123"
    assert cfg.repository == "memory"
