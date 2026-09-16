"""Every table belongs to exactly one database role; this map is the single
source of truth for the schema, the pool, and the migration chain."""

from enum import Enum


class DatabaseRole(str, Enum):
    CORE = "core"
    ACTIVITY = "activity"
    QUEUE = "queue"
    ADMIN = "admin"


TABLE_ROLES: dict[str, DatabaseRole] = {
    "orgs": DatabaseRole.CORE,
    "identities": DatabaseRole.CORE,
    "users": DatabaseRole.CORE,
    "memberships": DatabaseRole.CORE,
    "sessions": DatabaseRole.CORE,
    "api_keys": DatabaseRole.CORE,
    "work_items": DatabaseRole.QUEUE,
    "tasks": DatabaseRole.CORE,
    "idempotency_records": DatabaseRole.CORE,
    "events": DatabaseRole.ACTIVITY,
}


def role_for(table_name: str) -> DatabaseRole:
    try:
        return TABLE_ROLES[table_name]
    except KeyError:
        raise LookupError(
            f"table {table_name!r} has no database role; add it to TABLE_ROLES"
        ) from None
