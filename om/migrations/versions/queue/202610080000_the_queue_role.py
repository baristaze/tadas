"""The queue role: the work queue, fenced by one policy per login.

Revision ID: 202610080000
Revises: None
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610080000"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610080000_the_queue_role.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610080000_the_queue_role.down.sql")
