"""The size tally is the system's: `admin.platform_sizes` becomes
`admin.system_sizes`, its row and its key kept.

Revision ID: 202610210001
Revises: 202610210000
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610210001"
down_revision = "202610210000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ADMIN, "202610210001_the_size_tally_is_the_systems.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ADMIN, "202610210001_the_size_tally_is_the_systems.down.sql")
