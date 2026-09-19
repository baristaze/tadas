"""The migration runner: one Alembic chain and one version table per role,
each migration a pair of hand-written SQL files behind a thin wrapper.

Run as a module: `python -m tadas.om.storage.migrate upgrade --all`.
"""

import argparse
import asyncio
import importlib
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from alembic import command, op
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, MetaData
from sqlalchemy.ext.asyncio import create_async_engine

from tadas.om.storage.roles import TABLE_ROLES, DatabaseRole, role_for
from tadas.om.storage.settings import StorageSettings
from tadas.om.storage.tables.base import Base

MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "migrations"
VERSION_TABLE = "alembic_version"
_SCHEMA_REF = re.compile(r"\b(core|activity|queue|admin)\.([a-z_][a-z0-9_]*)")
_INDEX_REF = re.compile(
    r"\b(?:DROP|ALTER) INDEX\s+(?:IF EXISTS\s+)?(core|activity|queue|admin)\.([a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)


def alembic_config(role: DatabaseRole, url: str | None = None) -> Config:
    config = Config(str(MIGRATIONS_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("version_locations", str(MIGRATIONS_DIR / "versions" / role.value))
    if url is not None:
        config.set_main_option("sqlalchemy.url", url)
    config.attributes["role"] = role
    return config


def head(role: DatabaseRole) -> str | None:
    """The single head of a role's chain; more than one is a real conflict."""
    heads = ScriptDirectory.from_config(alembic_config(role)).get_heads()
    if len(heads) > 1:
        raise RuntimeError(f"role {role.value} has {len(heads)} heads: {heads}")
    return heads[0] if heads else None


def split_statements(sql: str) -> list[str]:
    """Hand-written DDL without function bodies splits on the semicolon."""
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    return [part.strip() for part in "\n".join(lines).split(";") if part.strip()]


def check_role_of_sql(role: DatabaseRole, sql: str) -> None:
    """Refuses a file that names a table of another role, by schema or by the role map.
    A dropped or altered index is schema-qualified too; only its schema is checked."""
    for schema, index in _INDEX_REF.findall(sql):
        if schema != role.value:
            raise RuntimeError(f"{role.value} migration drops index {schema}.{index}")
    for schema, table in _SCHEMA_REF.findall(_INDEX_REF.sub("", sql)):
        if schema != role.value:
            raise RuntimeError(f"{role.value} migration references {schema}.{table}")
        if table != VERSION_TABLE and role_for(table) is not role:
            raise RuntimeError(f"table {table} belongs to role {role_for(table).value}")


def run_sql(role: DatabaseRole, filename: str) -> None:
    """Called by a wrapper under versions/<role>/ to execute sql/<role>/<filename>."""
    sql = (MIGRATIONS_DIR / "sql" / role.value / filename).read_text()
    check_role_of_sql(role, sql)
    bind = op.get_bind()
    for statement in split_statements(sql):
        bind.exec_driver_sql(statement)


def load_tables() -> None:
    """Imports every namespace's table modules so Base.metadata holds them all.
    Without this the CLI compares an empty metadata and reports every migrated
    table as drift; a table named in TABLE_ROLES but never defined is refused."""
    om_root = Path(__file__).resolve().parents[1]
    for path in sorted(om_root.glob("*/storage/tables/*.py")):
        if path.stem != "__init__":
            relative = path.relative_to(om_root).with_suffix("")
            importlib.import_module(f"tadas.om.{'.'.join(relative.parts)}")
    missing = sorted(
        name for name in TABLE_ROLES if name not in {t.name for t in Base.metadata.tables.values()}
    )
    if missing:
        raise RuntimeError(f"tables in TABLE_ROLES without an ORM definition: {missing}")


def role_metadata(role: DatabaseRole) -> MetaData:
    load_tables()
    metadata = MetaData(naming_convention=Base.metadata.naming_convention)
    for table in Base.metadata.tables.values():
        if table.schema == role.value:
            table.to_metadata(metadata)
    return metadata


def schema_diff(connection: Connection, role: DatabaseRole) -> list[Any]:
    """The differences between the ORM metadata and the migrated schema of one role."""

    def include_name(name: str | None, type_: str, parent_names: dict[str, Any]) -> bool:
        if type_ == "schema":
            return name == role.value
        if type_ == "table":
            return name != VERSION_TABLE
        return True

    context = MigrationContext.configure(
        connection,
        opts={
            "include_schemas": True,
            "include_name": include_name,
            "compare_type": True,
            "compare_server_default": False,
        },
    )
    return compare_metadata(context, role_metadata(role))


async def _with_connection(url: str, work: Callable[[Connection], Any]) -> Any:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            return await connection.run_sync(work)
    finally:
        await engine.dispose()


async def upgrade(role: DatabaseRole, url: str, revision: str = "head") -> None:
    def work(connection: Connection) -> None:
        config = alembic_config(role)
        config.attributes["connection"] = connection
        command.upgrade(config, revision)

    await _with_connection(url, work)


async def downgrade(role: DatabaseRole, url: str, revision: str) -> None:
    def work(connection: Connection) -> None:
        config = alembic_config(role)
        config.attributes["connection"] = connection
        command.downgrade(config, revision)

    await _with_connection(url, work)


async def check(role: DatabaseRole, url: str) -> list[Any]:
    return await _with_connection(url, lambda connection: schema_diff(connection, role))


async def upgrade_all(urls: dict[DatabaseRole, str]) -> None:
    for role in DatabaseRole:
        await upgrade(role, urls[role])


def _roles_from_args(args: argparse.Namespace) -> list[DatabaseRole]:
    if args.all and args.role:
        raise SystemExit("name --role or --all, not both")
    if args.all:
        return list(DatabaseRole)
    if args.role:
        return [DatabaseRole(args.role)]
    raise SystemExit("refusing to guess: name --role <role> or --all")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tadas-migrate")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("upgrade", "downgrade", "check"):
        p = sub.add_parser(name)
        p.add_argument("--role", choices=[r.value for r in DatabaseRole])
        p.add_argument("--all", action="store_true")
        p.add_argument(
            "--local",
            action="store_true",
            help="refuse a database whose host is not local; every Makefile target passes it",
        )
        if name == "downgrade":
            p.add_argument("--to", required=True, help="revision, or -1 for one step")
    args = parser.parse_args(argv)
    settings = StorageSettings()
    if args.local:
        settings.refuse_remote()
    urls = settings.role_urls()
    roles = _roles_from_args(args)

    async def run() -> int:
        failed = 0
        for role in roles:
            if args.command == "upgrade":
                await upgrade(role, urls[role])
                print(f"{role.value}: upgraded to {head(role) or 'empty'}")
            elif args.command == "downgrade":
                await downgrade(role, urls[role], args.to)
                print(f"{role.value}: downgraded to {args.to}")
            else:
                diff = await check(role, urls[role])
                print(f"{role.value}: {'in sync' if not diff else diff}")
                failed += bool(diff)
        return 1 if failed else 0

    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
