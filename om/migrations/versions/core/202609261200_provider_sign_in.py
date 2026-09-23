"""Sign-in through the identity provider: an identity's issuer and subject,
an org's organization at the provider, the invitations table, and the
password hash left nullable and unread.

Revision ID: 202609261200
Revises: 202609250001
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202609261200"
down_revision = "202609250001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609261200_provider_sign_in.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202609261200_provider_sign_in.down.sql")
