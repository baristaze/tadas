"""The admin role, the operator plane's own: the system's size as the sweep
last counted it.

Revision ID: 202610210002
Revises: None
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610210002"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ADMIN, "202610210002_folded_admin_revisions.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ADMIN, "202610210002_folded_admin_revisions.down.sql")
