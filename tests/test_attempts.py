from datetime import timedelta

from app.services.attempts import AttemptLimiter

from .conftest import berlin

T0 = berlin(2026, 11, 24, 10)


def test_five_failures_lock_then_window_slides():
    lim = AttemptLimiter(limit=5, window=timedelta(minutes=1))
    for i in range(5):
        assert lim.retry_after("hub", T0 + timedelta(seconds=i)) is None
        lim.record_failure("hub", T0 + timedelta(seconds=i))
    wait = lim.retry_after("hub", T0 + timedelta(seconds=10))
    assert wait == timedelta(seconds=50)  # ältester Versuch (T0) fällt nach 60 s heraus
    assert lim.retry_after("hub", T0 + timedelta(seconds=60)) is None
    assert lim.remaining("hub", T0 + timedelta(seconds=60)) == 1


def test_keys_are_independent():
    lim = AttemptLimiter(limit=1)
    lim.record_failure("a", T0)
    assert lim.retry_after("a", T0) is not None
    assert lim.retry_after("b", T0) is None
