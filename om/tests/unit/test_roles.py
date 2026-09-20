"""Every table has one role, the role is its schema, and nothing crosses one."""

import importlib
import pkgutil

import pytest
from sqlalchemy import Column, MetaData, Table, Uuid, select

import tadas.om
from tadas.om.exceptions import CrossRoleStatement
from tadas.om.storage.impl.pg_base import role_of
from tadas.om.storage.roles import TABLE_ROLES, DatabaseRole, role_for
from tadas.om.storage.tables.base import Base
from tadas.om.tenancy.storage.tables.orgs import Orgs


def import_every_table_module() -> None:
    for module in pkgutil.walk_packages(tadas.om.__path__, prefix="tadas.om."):
        if ".storage.tables." in module.name:
            importlib.import_module(module.name)


def test_every_table_has_a_role_and_lives_in_its_schema() -> None:
    import_every_table_module()
    assert Base.metadata.tables, "no tables were imported"
    for table in Base.metadata.tables.values():
        role = role_for(table.name)
        assert table.schema == role.value, f"{table.name} is in {table.schema}, role says {role}"


def test_no_foreign_key_crosses_a_role() -> None:
    import_every_table_module()
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            assert role_for(fk.column.table.name) is role_for(table.name)


def test_every_mapped_table_is_in_the_role_map() -> None:
    import_every_table_module()
    for name in Base.metadata.tables:
        assert name.split(".")[-1] in TABLE_ROLES


def test_unmapped_table_is_refused() -> None:
    with pytest.raises(LookupError):
        role_for("not_a_table")


def test_a_statement_spanning_roles_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(TABLE_ROLES, "probe_activity", DatabaseRole.ACTIVITY)
    probe = Table("probe_activity", MetaData(), Column("id", Uuid), schema="activity")
    assert role_of(select(Orgs)) is DatabaseRole.CORE
    assert role_of(Orgs) is DatabaseRole.CORE
    with pytest.raises(CrossRoleStatement):
        role_of(select(Orgs.id, probe.c.id))


async def test_an_outbox_row_outside_the_core_role_is_refused() -> None:
    # The outbox lives in core; a queue-role write may not carry an outbox row,
    # or the session would hold two roles in one transaction.
    from tadas.om.base import new_id, utcnow
    from tadas.om.outbox.types.row import OutboxRow
    from tadas.om.storage.impl.pg_base import PgStorageBase
    from tadas.om.work.storage.tables.work_items import WorkItems

    row = OutboxRow(
        id=new_id(),
        created_at=utcnow(),
        kind="work.item.created",
        target_id=new_id(),
        actor_id=new_id(),
        request_id=new_id(),
        app="worker",
    )

    base = PgStorageBase({})  # no sessions: the role check fires before one is opened
    with pytest.raises(CrossRoleStatement):
        await base._upsert(WorkItems, new_id(), row, (row,))
