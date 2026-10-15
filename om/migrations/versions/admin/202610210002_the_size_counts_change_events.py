"""The size tally counts change events: `events_last_24h` becomes
`change_events_last_24h` on `admin.system_sizes`, its row kept.

Revision ID: 202610210002
Revises: 202610210001
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610210002"
down_revision = "202610210001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ADMIN, "202610210002_the_size_counts_change_events.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ADMIN, "202610210002_the_size_counts_change_events.down.sql")
