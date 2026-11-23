from datetime import timedelta

from app.domain.availability import count_free_devices, find_free_device, is_device_free
from app.domain.models import DeviceStatus, ReservationStatus

from .conftest import berlin, make_device, make_reservation

BUFFER = timedelta(minutes=30)
START = berlin(2026, 12, 1, 9)
END = START + timedelta(days=1)


def test_free_without_reservations():
    assert is_device_free(make_device(), [], START, END, BUFFER)


def test_overlap_blocks():
    r = make_reservation(start=START + timedelta(hours=5), status=ReservationStatus.CONFIRMED)
    assert not is_device_free(make_device(), [r], START, END, BUFFER)


def test_back_to_back_needs_buffer():
    # bestehende Miete endet genau, wenn die neue beginnt → Puffer fehlt
    r = make_reservation(start=START - timedelta(days=1), status=ReservationStatus.CONFIRMED)
    assert not is_device_free(make_device(), [r], START, END, BUFFER)


def test_after_buffer_is_free():
    r = make_reservation(start=START - timedelta(days=1, minutes=30), status=ReservationStatus.CONFIRMED)
    assert is_device_free(make_device(), [r], START, END, BUFFER)


def test_new_rental_buffer_must_not_hit_later_rental():
    later = make_reservation(start=END + timedelta(minutes=10), status=ReservationStatus.PENDING)
    assert not is_device_free(make_device(), [later], START, END, BUFFER)


def test_cancelled_and_finished_do_not_block():
    blocking_free = [
        ReservationStatus.CANCELLED_AUTO,
        ReservationStatus.CANCELLED_BY_CUSTOMER,
        ReservationStatus.NO_SHOW,
        ReservationStatus.RETURNED,
    ]
    rs = [make_reservation(id=s.value, start=START, status=s) for s in blocking_free]
    assert is_device_free(make_device(), rs, START, END, BUFFER)


def test_maintenance_never_free():
    d = make_device(status=DeviceStatus.MAINTENANCE)
    assert not is_device_free(d, [], START, END, BUFFER)


def test_other_device_does_not_block():
    r = make_reservation(device_id="d2", start=START, status=ReservationStatus.CONFIRMED)
    assert is_device_free(make_device("d1"), [r], START, END, BUFFER)


def test_find_free_device_picks_lowest_locker_and_skips_busy():
    d1 = make_device("d1", locker=3)
    d2 = make_device("d2", locker=1)
    d3 = make_device("d3", locker=2)
    busy = make_reservation(device_id="d2", start=START, status=ReservationStatus.CONFIRMED)
    found = find_free_device([d1, d2, d3], [busy], "t1", "h1", START, END, BUFFER)
    assert found is d3


def test_find_free_device_respects_type_and_hub():
    devices = [make_device("d1", type_id="t2"), make_device("d2", hub_id="h2")]
    assert find_free_device(devices, [], "t1", "h1", START, END, BUFFER) is None


def test_count_free_devices():
    devices = [make_device("d1"), make_device("d2", locker=2), make_device("d3", status=DeviceStatus.MAINTENANCE)]
    busy = make_reservation(device_id="d1", start=START, status=ReservationStatus.PICKED_UP)
    assert count_free_devices(devices, [busy], "t1", "h1", START, END, BUFFER) == 1
