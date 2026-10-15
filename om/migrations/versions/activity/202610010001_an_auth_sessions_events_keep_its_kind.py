"""An auth session's change events read under its kind: the events of kind
`tenancy.session.*` become `tenancy.auth_session.*` in place, each row kept.

Revision ID: 202610010001
Revises: 202610010000
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610010001"
down_revision = "202610010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610010001_an_auth_sessions_events_keep_its_kind.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610010001_an_auth_sessions_events_keep_its_kind.down.sql")
