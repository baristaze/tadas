"""Alembic environment: one chain and one version table per role. The role
comes from `config.attributes["role"]`, set by `tadas.om.storage.migrate`;
running without one is refused so a role is never migrated by accident."""

import asyncio

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from tadas.om.storage.migrate import VERSION_TABLE
from tadas.om.storage.roles import DatabaseRole

config = context.config


def required_role() -> DatabaseRole:
    found: DatabaseRole | None = config.attributes.get("role")
    if found is None:
        raise SystemExit("refusing to migrate without a role; run through tadas.om.storage.migrate")
    return found


role = required_role()


def run_migrations(connection: Connection) -> None:
    connection.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{role.value}"')
    context.configure(
        connection=connection,
        target_metadata=None,
        version_table=VERSION_TABLE,
        version_table_schema=role.value,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_with_new_engine() -> None:
    engine = create_async_engine(config.get_main_option("sqlalchemy.url") or "")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("offline mode is not supported; migrations run against a database")

connection = config.attributes.get("connection")
if connection is not None:
    run_migrations(connection)
else:
    asyncio.run(run_with_new_engine())
