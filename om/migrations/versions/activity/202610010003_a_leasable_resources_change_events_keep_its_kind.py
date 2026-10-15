"""A leasable resource's change events read under its kind: the events of kind
`leases.resource.*` become `leases.leasable_resource.*` in place.

Revision ID: 202610010003
Revises: 202610010002
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610010003"
down_revision = "202610010002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(
        DatabaseRole.ACTIVITY,
        "202610010003_a_leasable_resources_change_events_keep_its_kind.up.sql",
    )


def downgrade() -> None:
    run_sql(
        DatabaseRole.ACTIVITY,
        "202610010003_a_leasable_resources_change_events_keep_its_kind.down.sql",
    )
