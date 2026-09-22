"""The tenancy namespace's pure rules."""

from datetime import UTC, datetime, timedelta

import pytest

from tadas.om.tenancy.rules import (
    check_email,
    check_sign_up,
    email_digest,
    is_platform_email,
    matching_totp_step,
    otpauth_uri,
    sign_in_delay,
    totp_code,
    totp_step,
)

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


def test_a_totp_code_is_rfc_6238s() -> None:
    """RFC 6238's SHA-1 test vector, cut to the six digits authenticators show:
    at 59 seconds the eight-digit code is 94287082."""
    secret = b"12345678901234567890"
    at = datetime(1970, 1, 1, 0, 0, 59, tzinfo=UTC)
    assert totp_step(at) == 1
    assert totp_code(secret, 1) == "287082"
    assert totp_code(secret, totp_step(datetime(2009, 2, 13, 23, 31, 30, tzinfo=UTC))) == "005924"


def test_a_code_matches_one_step_either_side_and_nothing_else() -> None:
    secret = b"12345678901234567890"
    now = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    step = totp_step(now)
    for offset in (-1, 0, 1):
        assert matching_totp_step(secret, totp_code(secret, step + offset), now) == step + offset
    assert matching_totp_step(secret, totp_code(secret, step + 2), now) is None
    assert matching_totp_step(secret, "12345", now) is None
    assert matching_totp_step(secret, "abcdef", now) is None


def test_the_otpauth_uri_carries_the_secret_the_account_and_the_issuer() -> None:
    uri = otpauth_uri(b"12345678901234567890", "root@example.test", "Tadas")
    assert uri == (
        "otpauth://totp/Tadas%3Aroot%40example.test?secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
        "&issuer=Tadas&algorithm=SHA1&digits=6&period=30"
    )


def test_the_email_digest_is_the_sha_256_of_the_address_as_given() -> None:
    assert email_digest("ann@example.test") == (
        "eff90234b5c0d7bb3000e7e2faa01214ffecef55617da623def7482021cc124f"
    )
    assert email_digest("Ann@example.test") != email_digest("ann@example.test")


@pytest.mark.parametrize(
    "email", ["ann", "ann@", "@example.test", "ann@example", " ann@example.test", "a\\b@x.test"]
)
def test_an_address_of_the_wrong_shape_is_refused(email: str) -> None:
    with pytest.raises(ValueError):
        check_email(email)


def test_the_platforms_own_addresses_are_refused_at_sign_up() -> None:
    assert is_platform_email("provisioner@platform.tadas.invalid")
    assert not is_platform_email("provisioner@example.test")
    with pytest.raises(ValueError, match="belongs to the platform"):
        check_sign_up("smoke@platform.tadas.invalid", "pw-12345678", "S", "Smoke", "smoke")
