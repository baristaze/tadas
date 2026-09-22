"""The four profiles: named, frozen, and ordered from light to stress."""

import dataclasses
from itertools import pairwise

import pytest

from tadas.ops.profiles import HEAVY, LIGHT, PROFILES, REGULAR, STRESS, profile_named


def test_four_profiles_ship_and_grow_from_light_to_stress() -> None:
    assert list(PROFILES) == ["light", "regular", "heavy", "stress"]
    chain = [LIGHT, REGULAR, HEAVY, STRESS]
    for lighter, heavier in pairwise(chain):
        assert heavier.people > lighter.people
        assert heavier.concurrency > lighter.concurrency
        assert heavier.think_seconds[1] <= lighter.think_seconds[1]


def test_a_profile_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        LIGHT.concurrency = 99  # type: ignore[misc]


def test_an_unknown_profile_is_named_in_the_error() -> None:
    with pytest.raises(ValueError, match="unknown profile 'gentle'"):
        profile_named("gentle")


def test_every_profile_stays_under_the_login_rate_limit() -> None:
    """A run signs each person in once and drives at most one session per
    worker, so its sign-ins are its concurrency. The login budget is sized
    for a crowd behind one address, so every profile fits, and a generator
    is never refused for driving the load it was asked to drive."""
    login_rate_limit = 200  # the API's `login_rate_limit`, per address
    assert all(p.concurrency <= login_rate_limit for p in (LIGHT, REGULAR, HEAVY, STRESS))
