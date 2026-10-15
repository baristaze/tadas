"""The not-null constraint on a work item's lane is named for its column,
`work_items_lane_not_null`, as Postgres names it on a table made in one step.

Revision ID: 202610080003
Revises: 202610080002
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610080003"
down_revision = "202610080002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610080003_the_lanes_not_null_is_named_for_its_column.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610080003_the_lanes_not_null_is_named_for_its_column.down.sql")
