"""The leases listed newest first: the org's, and one resource's, each by an
index of its own.

Revision ID: 202610220003
Revises: 202610220002
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610220003"
down_revision = "202610220002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610220003_leases_listed_newest_first.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610220003_leases_listed_newest_first.down.sql")
