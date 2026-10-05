"""Store a content hash for uploaded photos so a resubmitted (reused) photo can be detected.

Used to reject a meter-reading photo that is byte-identical to one the same
account already submitted in an earlier period.
"""
from alembic import op
import sqlalchemy as sa

revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("application_files", sa.Column("content_hash", sa.String(64), nullable=True))
    op.create_index(op.f("ix_application_files_content_hash"), "application_files", ["content_hash"])


def downgrade():
    op.drop_index(op.f("ix_application_files_content_hash"), table_name="application_files")
    op.drop_column("application_files", "content_hash")
