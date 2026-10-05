"""Remove duplicate unique constraints left over by earlier migrations.

api_keys.key_hash and blocked_ips.ip are declared as `unique=True, index=True`
in models.py, which SQLAlchemy represents as a single unique index. The
migrations that created these tables additionally added a separate named
UniqueConstraint, so the schema carried two redundant unique constraints per
column and `alembic check` reported drift against a fresh database.
"""
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("uq_api_keys_key_hash", "api_keys", type_="unique")
    op.drop_constraint("uq_blocked_ips_ip", "blocked_ips", type_="unique")
    op.drop_index("ix_blocked_ips_ip", table_name="blocked_ips")
    op.create_index("ix_blocked_ips_ip", "blocked_ips", ["ip"], unique=True)


def downgrade():
    op.drop_index("ix_blocked_ips_ip", table_name="blocked_ips")
    op.create_index("ix_blocked_ips_ip", "blocked_ips", ["ip"], unique=False)
    op.create_unique_constraint("uq_blocked_ips_ip", "blocked_ips", ["ip"])
    op.create_unique_constraint("uq_api_keys_key_hash", "api_keys", ["key_hash"])
