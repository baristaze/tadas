"""Every role's migrated schema agrees with the ORM metadata, the latest
revision of every role downgrades and upgrades again, and the logins are safe
to make twice."""

import pytest

from tadas.om.storage.migrate import check, downgrade, ensure_logins_at, head, upgrade
from tadas.om.storage.roles import DatabaseRole
from tadas.om.storage.settings import MigrationSettings

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("role", list(DatabaseRole))
async def test_orm_and_schema_agree(migrated: dict[DatabaseRole, str], role: DatabaseRole) -> None:
    assert await check(role, migrated[role]) == []


@pytest.mark.parametrize("role", list(DatabaseRole))
async def test_latest_revision_round_trips(
    migrated: dict[DatabaseRole, str], role: DatabaseRole
) -> None:
    if head(role) is None:
        pytest.skip(f"role {role.value} has no migrations yet")
    await downgrade(role, migrated[role], "-1")
    await upgrade(role, migrated[role])
    assert await check(role, migrated[role]) == []


async def test_ensure_logins_runs_again_on_a_migrated_database(
    migration_settings: MigrationSettings, migrated: dict[DatabaseRole, str]
) -> None:
    """The deploy runs it before every migrate, so the second run over a
    database it already shaped changes nothing and fails nothing."""
    settings = migration_settings
    await ensure_logins_at(settings.master_url(), settings.login_passwords())
    for role in DatabaseRole:
        assert await check(role, migrated[role]) == []
