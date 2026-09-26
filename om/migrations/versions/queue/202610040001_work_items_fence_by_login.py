"""The queue's fence is one policy per login.

Revision ID: 202610040001
Revises: 202610040000
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610040001"
down_revision = "202610040000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610040001_work_items_fence_by_login.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610040001_work_items_fence_by_login.down.sql")
