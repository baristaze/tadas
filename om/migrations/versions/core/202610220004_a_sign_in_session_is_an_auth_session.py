"""A sign-in session is an auth session: `core.sessions` becomes
`core.auth_sessions`, every row kept, and the stored values that name it move
in place: the credential kind `session_token` becomes `auth_session_token` on
the sessions and the socket tickets, and the outbox kinds `tenancy.session.*`
become `tenancy.auth_session.*`.

Revision ID: 202610220004
Revises: 202610220003
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610220004"
down_revision = "202610220003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610220004_a_sign_in_session_is_an_auth_session.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610220004_a_sign_in_session_is_an_auth_session.down.sql")
