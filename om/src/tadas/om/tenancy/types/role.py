"""The role-to-permission table and the role ranks: pure rules of the
tenancy namespace over the `Role` and `Permission` the context module
declares. Permissions are a function of role; a context is built with the
tuple this table gives."""

from tadas.om.opcontext import Permission, Role

__all__ = ["ROLE_PERMISSIONS", "ROLE_RANK", "permissions_of"]

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
    Role.SERVICE: 1,
    Role.MEMBER: 1,
    Role.ADMIN: 2,
    Role.OWNER: 3,
}
"""Used to cap an issued credential at its issuer's role."""


def permissions_of(role: Role) -> tuple[Permission, ...]:
    return ROLE_PERMISSIONS[role]
