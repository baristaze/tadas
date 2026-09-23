"""The billing swimlane: an org's billing account and the processor's
deliveries already applied, each under the tenant fence.

Revision ID: 202609250100
Revises: 202609250001
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202609250100"
down_revision = "202609250001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609250100_billing.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609250100_billing.down.sql")
