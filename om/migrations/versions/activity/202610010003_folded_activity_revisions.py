"""The activity role: each tenant's change-event stream and its cursor.

Revision ID: 202610010003
Revises: None
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610010003"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610010003_folded_activity_revisions.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610010003_folded_activity_revisions.down.sql")
