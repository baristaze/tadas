"""Roles, permissions, and the one table that maps one to the other.
Permissions are a pure function of role, declared here in the tenancy
namespace; `OpContext` reads this table and nothing else does."""

from enum import Enum


class Role(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"
    SERVICE = "service"  # a worker acting on a person's earlier request


class Permission(str, Enum):
    READ = "read"
    WRITE = "write"
    MANAGE_MEMBERS = "manage_members"
    MANAGE_KEYS = "manage_keys"


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
    Role.SERVICE: (Permission.READ, Permission.WRITE),
}

ROLE_RANK: dict[Role, int] = {
    Role.VIEWER: 0,
    Role.SERVICE: 1,
    Role.MEMBER: 1,
    Role.ADMIN: 2,
    Role.OWNER: 3,
}
"""Used to cap an issued credential at its issuer's role."""


class CredentialKind(str, Enum):
    API_KEY = "api_key"
    SESSION_TOKEN = "session_token"
    LOGIN = "login"
    SOCKET_TICKET = "socket_ticket"
    INTERNAL = "internal"
