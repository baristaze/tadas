"""The requeue of expired leases reads one index across tenants.

Revision ID: 202610030000
Revises: 202609240100
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610030000"
down_revision = "202609240100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610030000_expired_lease_index.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610030000_expired_lease_index.down.sql")
