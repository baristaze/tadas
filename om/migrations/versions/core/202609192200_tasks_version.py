"""Optimistic concurrency on tasks: the version column the compare-and-set
conditions every update, move, and soft delete on.

Revision ID: 202609192200
Revises: 202609192100
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202609192200"
down_revision = "202609192100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609192200_tasks_version.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609192200_tasks_version.down.sql")
