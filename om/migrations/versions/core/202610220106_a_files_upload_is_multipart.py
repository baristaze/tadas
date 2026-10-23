"""A file's upload is multipart: its row names the store's upload id, which
every part, the resume, and the complete name.

Revision ID: 202610220106
Revises: 202610220006
"""

from tadas.om.storage.migrate import run_sql
from tadas.om.storage.roles import DatabaseRole

revision = "202610220106"
down_revision = "202610220006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610220106_a_files_upload_is_multipart.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610220106_a_files_upload_is_multipart.down.sql")
