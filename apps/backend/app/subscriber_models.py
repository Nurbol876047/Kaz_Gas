"""Subscriber registry is independent of Telegram user registration."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, utcnow


class SubscriberAccount(Base):
    __tablename__ = "subscriber_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_number: Mapped[str] = mapped_column(String(20), unique=True)
    meter_number: Mapped[str] = mapped_column(String(40), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    binding_note: Mapped[str | None] = mapped_column(String(300))
    version: Mapped[int] = mapped_column(default=1)
    last_reading: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    last_period: Mapped[date | None] = mapped_column(Date)
    last_reminder_period: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MeterReading(Base):
    __tablename__ = "meter_readings"
    __table_args__ = (
        UniqueConstraint("telegram_user_id", "idempotency_key"),
        CheckConstraint("value IS NULL OR value >= 0", name="nonnegative_value"),
        CheckConstraint("status IN ('PENDING', 'ACCEPTED', 'REJECTED')", name="reading_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[int] = mapped_column(ForeignKey("subscriber_accounts.id"), index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger)
    idempotency_key: Mapped[str] = mapped_column(String(36))
    period: Mapped[date] = mapped_column(Date)
    # The resident only submits a photo; the numeric value is entered by the admin during review.
    photo_id: Mapped[str] = mapped_column(ForeignKey("application_files.id"))
    value: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    consumption: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    status: Mapped[str] = mapped_column(String(12), default="PENDING")
    review_note: Mapped[str | None] = mapped_column(String(500))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("admins.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
