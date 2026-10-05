"""Subscriber registry, verified account binding and meter readings."""
from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "subscriber_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_number", sa.String(20), nullable=False, unique=True),
        sa.Column("meter_number", sa.String(40), nullable=False, unique=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("address", sa.String(500), nullable=False),
        sa.Column("phone", sa.String(16)),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger()),
        sa.Column("binding_note", sa.String(300)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("last_reading", sa.Numeric(14, 3)),
        sa.Column("last_period", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_subscriber_accounts_telegram_user_id", "subscriber_accounts", ["telegram_user_id"])
    op.create_table(
        "meter_readings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("subscriber_accounts.id"), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(36), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(14, 3), nullable=False),
        sa.Column("consumption", sa.Numeric(14, 3)),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("review_note", sa.String(500)),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("admins.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("telegram_user_id", "idempotency_key"),
        sa.CheckConstraint("value >= 0", name="nonnegative_value"),
        sa.CheckConstraint("status IN ('PENDING', 'ACCEPTED', 'REJECTED')", name="reading_status"),
    )
    op.create_index("ix_meter_readings_account_id", "meter_readings", ["account_id"])
    op.add_column("applications", sa.Column("subscriber_verified", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column("applications", "subscriber_verified", server_default=None)


def downgrade():
    op.drop_column("applications", "subscriber_verified")
    op.drop_table("meter_readings")
    op.drop_table("subscriber_accounts")
