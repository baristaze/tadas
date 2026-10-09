"""Leases on a resource: the resources with their anchors, the leases, and
the requests in line, each with the tenant's fence (ADR 0086).

Revision ID: 202610220001
Revises: 202610220000
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610220001"
down_revision = "202610220000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610220001_leases_on_a_resource.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610220001_leases_on_a_resource.down.sql")
