"""The position leaves the mapping; a trigger keeps it the rank's float for
the release before, which still reads it (ADR 0050).

Revision ID: 202610200000
Revises: 202610170000
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610200000"
down_revision = "202610170000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610200000_task_position_from_rank.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610200000_task_position_from_rank.down.sql")
