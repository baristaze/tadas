"""The role ladder is held to the permission table: a role at most another
holds a subset of its permissions, and the role reserved for services is
not a rung, so no comparison places it."""

import itertools

import pytest

from tadas.om.opcontext import Role
from tadas.om.tenancy.rules import capped_role, role_at_most
from tadas.om.tenancy.types.role import (
    PERSON_ROLES,
    ROLE_PERMISSIONS,
    ROLE_RANK,
    permissions_of,
)


def test_the_ladder_holds_the_person_roles_and_only_them() -> None:
    assert set(ROLE_RANK) == set(Role) - {Role.SERVICE}
    assert set(PERSON_ROLES) == set(ROLE_RANK)
    assert set(ROLE_PERMISSIONS) == set(Role)


@pytest.mark.parametrize("requested,ceiling", list(itertools.product(PERSON_ROLES, repeat=2)))
def test_at_most_means_a_subset_of_permissions(requested: Role, ceiling: Role) -> None:
    if role_at_most(requested, ceiling):
        assert set(permissions_of(requested)) <= set(permissions_of(ceiling))
        assert capped_role(requested, ceiling) is requested
    else:
        assert capped_role(requested, ceiling) is ceiling


@pytest.mark.parametrize("role", PERSON_ROLES)
def test_every_role_is_at_most_itself(role: Role) -> None:
    assert role_at_most(role, role)


@pytest.mark.parametrize("other", PERSON_ROLES)
def test_the_service_role_is_no_rung(other: Role) -> None:
    # Apart from the ladder: at most no person role, no person role at most it.
    assert not role_at_most(Role.SERVICE, other)
    assert not role_at_most(other, Role.SERVICE)
    assert capped_role(Role.SERVICE, other) is other
    with pytest.raises(ValueError):
        capped_role(other, Role.SERVICE)
    assert not role_at_most(Role.SERVICE, Role.SERVICE)
