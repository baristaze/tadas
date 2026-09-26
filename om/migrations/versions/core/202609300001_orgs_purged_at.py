"""`orgs.purged_at`: a deleted tenant the sweep found nothing left of, which
it leaves out from then on.

Revision ID: 202609300001
Revises: 202609300000
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202609300001"
down_revision = "202609300000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609300001_orgs_purged_at.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609300001_orgs_purged_at.down.sql")
