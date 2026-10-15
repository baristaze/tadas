"""A queued wake names the leasable resource: a `WAKE_PARKED` item whose
reason is `resource` carries `leasable_resource`, in place.

Revision ID: 202610080002
Revises: 202610080001
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610080002"
down_revision = "202610080001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610080002_a_wake_names_the_leasable_resource.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610080002_a_wake_names_the_leasable_resource.down.sql")
