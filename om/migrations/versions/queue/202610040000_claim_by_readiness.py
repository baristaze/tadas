"""The claim walks the ready items in the order they became ready.

Revision ID: 202610040000
Revises: 202609240100
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610040000"
down_revision = "202609240100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610040000_claim_by_readiness.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610040000_claim_by_readiness.down.sql")
