"""The core role: the tenancy swimlane, tasks, the idempotency markers, the
outbox, files, billing, Slack, and the orchestrations.

Revision ID: 202610200100
Revises: None
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610200100"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610200100_the_core_role.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610200100_the_core_role.down.sql")
