"""Track the last calendar month a meter-reading reminder was sent for an account.

Lets the notification worker send at most one reminder per subscriber per month,
without a separate scheduling table.
"""
from alembic import op
import sqlalchemy as sa

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("subscriber_accounts", sa.Column("last_reminder_period", sa.Date(), nullable=True))


def downgrade():
    op.drop_column("subscriber_accounts", "last_reminder_period")
