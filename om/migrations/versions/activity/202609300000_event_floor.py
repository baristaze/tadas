"""The event cursor carries the stream's floor; the stream is indexed on when
each event was produced.

Revision ID: 202609300000
Revises: 202609240000
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202609300000"
down_revision = "202609240000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202609300000_event_floor.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202609300000_event_floor.down.sql")
