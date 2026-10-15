"""The core role: the tenancy swimlane, tasks, the idempotency markers, the
outbox, files, billing, Slack, the orchestrations, and the leases on a
leasable resource.

Revision ID: 202610220005
Revises: None
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610220005"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610220005_folded_core_revisions.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610220005_folded_core_revisions.down.sql")
