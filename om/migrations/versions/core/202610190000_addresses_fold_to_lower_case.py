"""Every stored address folded to lower case, and the identity's digest
computed from the folded address; it stops, naming the rows, on two that
fold to one.

Revision ID: 202610190000
Revises: 202610170000
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610190000"
down_revision = "202610170000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610190000_addresses_fold_to_lower_case.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610190000_addresses_fold_to_lower_case.down.sql")
