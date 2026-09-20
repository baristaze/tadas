"""The role-to-permission table and the role ladder: pure rules of the
tenancy namespace over the `Role` and `Permission` the context module
declares. Permissions are a function of role; a context is built with the
tuple this table gives.

The ladder orders the person roles, and above means the permission set: a
role is at most another when its permissions are a subset of the other's,
and a unit test holds `ROLE_RANK` to `ROLE_PERMISSIONS`. The one place the
ladder is stricter than the sets is the top: the owner and the admin hold
the same permissions today, and the owner still ranks above, because the
owner is the tenant's founder and not a permission set. The role reserved
for services is not a rung: no credential a person mints carries it, and
every operation that issues one refuses it by name."""

from tadas.om.opcontext import Permission, Role

__all__ = ["PERSON_ROLES", "ROLE_PERMISSIONS", "ROLE_RANK", "permissions_of"]

ROLE_PERMISSIONS: dict[Role, tuple[Permission, ...]] = {
    Role.OWNER: (
        Permission.READ,
        Permission.WRITE,
        Permission.MANAGE_MEMBERS,
        Permission.MANAGE_KEYS,
    ),
    Role.ADMIN: (
        Permission.READ,
        Permission.WRITE,
        Permission.MANAGE_MEMBERS,
        Permission.MANAGE_KEYS,
    ),
    Role.MEMBER: (Permission.READ, Permission.WRITE, Permission.MANAGE_KEYS),
    Role.VIEWER: (Permission.READ,),
    Role.SERVICE: (Permission.READ, Permission.WRITE, Permission.MANAGE_MEMBERS),
}

ROLE_RANK: dict[Role, int] = {
    Role.VIEWER: 0,
    Role.MEMBER: 1,
    Role.ADMIN: 2,
    Role.OWNER: 3,
}
"""The ladder of the person roles, used to cap an issued credential and a
granted membership at the issuer's role. `Role.SERVICE` has no rank."""

PERSON_ROLES: tuple[Role, ...] = tuple(ROLE_RANK)
"""The roles a membership or a credential a person mints may carry."""


def permissions_of(role: Role) -> tuple[Permission, ...]:
    return ROLE_PERMISSIONS[role]
