"""An index under every purge statement the sweep runs: the outbox's dead
letters, deleted tasks, sessions and socket tickets by expiry, idempotency
records and Slack posts by birth.

Revision ID: 202609300000
Revises: 202609290000
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202609300000"
down_revision = "202609290000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609300000_purge_indexes.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609300000_purge_indexes.down.sql")
