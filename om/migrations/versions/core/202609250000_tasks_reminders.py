"""Reminders on tasks: the due time a person sets, and when its reminder went
out.

Revision ID: 202609250000
Revises: 202609240000
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202609250000"
down_revision = "202609240000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609250000_tasks_reminders.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609250000_tasks_reminders.down.sql")
