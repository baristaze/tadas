"""Events carry a kind, a target, and a payload.

Revision ID: 202609181203
Revises: 202609181001
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202609181203"
down_revision = "202609181001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202609181203_events_kind_target_payload.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202609181203_events_kind_target_payload.down.sql")
