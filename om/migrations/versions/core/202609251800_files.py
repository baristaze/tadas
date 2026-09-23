"""The media swimlane's file rows, with their tenant fence.

Revision ID: 202609251800
Revises: 202609251701
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202609251800"
down_revision = "202609251701"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609251800_files.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609251800_files.down.sql")
