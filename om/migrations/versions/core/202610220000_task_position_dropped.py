"""The contract half of ADR 0038: a task's position, the two triggers that
kept it the rank's float, and their functions leave the table. The release
before this one names the position in no statement.

Revision ID: 202610220000
Revises: 202610200100
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610220000"
down_revision = "202610200100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610220000_task_position_dropped.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610220000_task_position_dropped.down.sql")
