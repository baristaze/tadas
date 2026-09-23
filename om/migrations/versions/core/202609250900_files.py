"""The media swimlane's file rows, with their tenant fence.

Revision ID: 202609250900
Revises: 202609250001
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202609250900"
down_revision = "202609250001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609250900_files.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609250900_files.down.sql")
