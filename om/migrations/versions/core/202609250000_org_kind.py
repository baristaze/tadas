"""An org's kind, personal or team, and the person a personal org belongs to.

Revision ID: 202609250000
Revises: 202609240000
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202609250000"
down_revision = "202609240000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609250000_org_kind.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609250000_org_kind.down.sql")
