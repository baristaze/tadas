"""A tenant's own cap on a lane: one row per tenant and lane, under the
one policy every tenant table has.

Revision ID: 202610080001
Revises: 202610080000
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610080001"
down_revision = "202610080000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610080001_a_tenants_own_cap.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610080001_a_tenants_own_cap.down.sql")
