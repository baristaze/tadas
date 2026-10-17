"""The attempt at the org's customer on its billing account, which the
customer create's idempotency key carries.

Revision ID: 202610220006
Revises: 202610220005
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610220006"
down_revision = "202610220005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610220006_a_customer_attempt_on_the_billing_account.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610220006_a_customer_attempt_on_the_billing_account.down.sql")
