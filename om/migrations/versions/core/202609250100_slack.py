"""Slack: the channel an org connects, the one-time codes that connect one,
and the record of what was posted there.

Revision ID: 202609250100
Revises: 202609250000
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202609250100"
down_revision = "202609250000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609250100_slack.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609250100_slack.down.sql")
