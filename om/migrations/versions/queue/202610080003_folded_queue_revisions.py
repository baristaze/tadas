"""The queue role: the work queue, fenced by one policy per login, and each
tenant's own cap on a lane.

Revision ID: 202610080003
Revises: None
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610080003"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610080003_folded_queue_revisions.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610080003_folded_queue_revisions.down.sql")
