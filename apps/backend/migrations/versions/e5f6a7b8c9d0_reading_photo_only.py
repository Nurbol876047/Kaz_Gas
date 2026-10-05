"""Meter readings are submitted as a photo only; the admin enters the value on review.

Adds METER_READING_PHOTO to the file-type check constraint, links meter_readings
to the uploaded photo, and makes the resident-entered value nullable until review.
"""
from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    # METER_READING_PHOTO (19 chars) is longer than the column's original VARCHAR(14),
    # sized for the previous longest member GAS_LEAK_PHOTO.
    op.alter_column("application_files", "file_type", type_=sa.String(19), existing_type=sa.String(14))
    # op.f() marks these as literal existing names: they were created without going
    # through this naming-convention-aware helper, so re-wrapping without op.f()
    # would double-prefix them (e.g. ck_application_files_ck_application_files_filetype).
    op.drop_constraint(op.f("ck_application_files_filetype"), "application_files", type_="check")
    op.create_check_constraint(
        op.f("ck_application_files_filetype"),
        "application_files",
        "file_type IN ('METER_PHOTO', 'GAS_LEAK_PHOTO', 'METER_READING_PHOTO', 'OTHER')",
    )
    op.add_column("meter_readings", sa.Column("photo_id", sa.String(36), sa.ForeignKey("application_files.id"), nullable=False))
    op.alter_column("meter_readings", "value", existing_type=sa.Numeric(14, 3), nullable=True)
    # No op.f() here: "nonnegative_value" is the short label from the model source,
    # and the naming convention must expand it once to match the stored name
    # ck_meter_readings_nonnegative_value (unlike the already-expanded name above).
    op.drop_constraint("nonnegative_value", "meter_readings", type_="check")
    op.create_check_constraint("nonnegative_value", "meter_readings", "value IS NULL OR value >= 0")


def downgrade():
    op.drop_constraint("nonnegative_value", "meter_readings", type_="check")
    op.create_check_constraint("nonnegative_value", "meter_readings", "value >= 0")
    op.alter_column("meter_readings", "value", existing_type=sa.Numeric(14, 3), nullable=False)
    op.drop_column("meter_readings", "photo_id")
    op.drop_constraint(op.f("ck_application_files_filetype"), "application_files", type_="check")
    op.create_check_constraint(
        op.f("ck_application_files_filetype"),
        "application_files",
        "file_type IN ('METER_PHOTO', 'GAS_LEAK_PHOTO', 'OTHER')",
    )
    op.alter_column("application_files", "file_type", type_=sa.String(14), existing_type=sa.String(19))
