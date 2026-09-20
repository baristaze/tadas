"""The operator allowlist entry carries a role, `read` or `write`, in place
of the flag. A rename in one migration: ADR 0006 allows it before the first
deployment.

Revision ID: 202609201700
Revises: 202609201600
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202609201700"
down_revision = "202609201600"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609201700_operator_role.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609201700_operator_role.down.sql")
