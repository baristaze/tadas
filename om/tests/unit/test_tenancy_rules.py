"""The tenancy namespace's pure rules."""

from datetime import UTC, datetime, timedelta

from tadas.om.tenancy.rules import sign_in_delay

KNOBS = {"free": 3, "base": timedelta(seconds=1), "cap": timedelta(minutes=5)}


def test_the_sign_in_delay_grows_from_the_run_and_stops_at_its_cap() -> None:
    now = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    assert sign_in_delay(2, now, now, **KNOBS) == timedelta(0)
    assert sign_in_delay(3, now, now, **KNOBS) == timedelta(seconds=1)
    assert sign_in_delay(4, now, now, **KNOBS) == timedelta(seconds=2)
    assert sign_in_delay(8, now, now, **KNOBS) == timedelta(seconds=32)
    assert sign_in_delay(40, now, now, **KNOBS) == timedelta(minutes=5)


def test_the_sign_in_delay_counts_from_the_last_failure() -> None:
    now = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    assert sign_in_delay(4, now - timedelta(seconds=1), now, **KNOBS) == timedelta(seconds=1)
    assert sign_in_delay(4, now - timedelta(minutes=1), now, **KNOBS) == timedelta(0)
    assert sign_in_delay(9, None, now, **KNOBS) == timedelta(0)
