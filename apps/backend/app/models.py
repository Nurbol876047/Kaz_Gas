import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, utcnow


class ApplicationType(str, enum.Enum):
    METER_NOT_WORKING = "METER_NOT_WORKING"
    MPI_REMOVAL = "MPI_REMOVAL"
    GAS_LEAK = "GAS_LEAK"


class Status(str, enum.Enum):
    NEW = "NEW"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class Priority(str, enum.Enum):
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Role(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    DISPATCHER = "DISPATCHER"
    OPERATOR = "OPERATOR"


class FileType(str, enum.Enum):
    METER_PHOTO = "METER_PHOTO"
    GAS_LEAK_PHOTO = "GAS_LEAK_PHOTO"
    METER_READING_PHOTO = "METER_READING_PHOTO"
    OTHER = "OTHER"


def enum_col(cls, name=None):
    return Enum(
        cls,
        native_enum=False,
        create_constraint=True,
        name=name or cls.__name__.lower(),
    )


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


# =========================================================
# USERS
# =========================================================

class User(Timestamps, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
    )
    telegram_username: Mapped[str | None] = mapped_column(
        String(64),
    )
    first_name: Mapped[str] = mapped_column(
        String(256),
    )
    last_name: Mapped[str | None] = mapped_column(
        String(256),
    )
    phone_number: Mapped[str | None] = mapped_column(
        String(32),
    )


# =========================================================
# ADMINS
# =========================================================

class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(
        String(200),
    )
    email: Mapped[str] = mapped_column(
        String(254),
        unique=True,
    )
    password_hash: Mapped[str] = mapped_column(
        String(512),
    )
    role: Mapped[Role] = mapped_column(
        enum_col(Role),
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    token_hash: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )
    admin_id: Mapped[int] = mapped_column(
        ForeignKey("admins.id"),
        index=True,
    )
    csrf_token: Mapped[str] = mapped_column(
        String(100),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )


# =========================================================
# APPLICATIONS
# =========================================================

class Application(Timestamps, Base):
    __tablename__ = "applications"
    subscriber_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
        ),
        CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90",
            name="latitude",
        ),
        CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name="longitude",
        ),
        CheckConstraint(
            "application_type != 'GAS_LEAK' OR priority = 'CRITICAL'",
            name="critical_gas",
        ),
        CheckConstraint(
            "(application_type = 'MPI_REMOVAL' "
            "AND requested_date IS NOT NULL) "
            "OR "
            "(application_type != 'MPI_REMOVAL' "
            "AND latitude IS NOT NULL "
            "AND longitude IS NOT NULL)",
            name="required_fields",
        ),
        Index(
            "ix_applications_status_created",
            "status",
            "created_at",
        ),
        Index(
            "ix_applications_priority_created",
            "priority",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
    )

    application_number: Mapped[str] = mapped_column(
        String(50),
        unique=True,
    )

    idempotency_key: Mapped[str] = mapped_column(
        String(36),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        index=True,
    )

    personal_account: Mapped[str] = mapped_column(
        String(30),
        index=True,
    )

    application_type: Mapped[ApplicationType] = mapped_column(
        enum_col(ApplicationType),
        index=True,
    )

    status: Mapped[Status] = mapped_column(
        enum_col(Status),
        default=Status.NEW,
    )

    priority: Mapped[Priority] = mapped_column(
        enum_col(Priority),
        default=Priority.NORMAL,
    )

    requested_date: Mapped[date | None] = mapped_column(
        Date,
    )

    latitude: Mapped[float | None]
    longitude: Mapped[float | None]

    assigned_to: Mapped[int | None] = mapped_column(
        ForeignKey("admins.id"),
        index=True,
    )

    admin_comment: Mapped[str | None] = mapped_column(
        Text,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    version: Mapped[int] = mapped_column(
        default=1,
    )


class ApplicationFile(Base):
    __tablename__ = "application_files"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id"),
        index=True,
    )

    owner_telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True,
    )

    file_type: Mapped[FileType] = mapped_column(
        enum_col(FileType),
    )

    telegram_file_id: Mapped[str] = mapped_column(
        String(512),
    )

    storage_url: Mapped[str] = mapped_column(
        String(100),
        unique=True,
    )

    # SHA-256 of the normalized image bytes; lets callers detect the same photo being resubmitted.
    content_hash: Mapped[str | None] = mapped_column(
        String(64),
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        index=True,
    )


class ApplicationHistory(Base):
    __tablename__ = "application_history"

    id: Mapped[int] = mapped_column(
        primary_key=True,
    )

    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id"),
        index=True,
    )

    admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admins.id"),
    )

    old_status: Mapped[Status | None] = mapped_column(
        enum_col(Status, "old_status"),
    )

    new_status: Mapped[Status] = mapped_column(
        enum_col(Status, "new_status"),
    )

    comment: Mapped[str | None] = mapped_column(
        Text,
    )

    public_comment: Mapped[bool] = mapped_column(
        default=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )


# =========================================================
# AUDIT LOG
# =========================================================

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(
        primary_key=True,
    )

    admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admins.id"),
    )

    action: Mapped[str] = mapped_column(
        String(100),
    )

    target: Mapped[str] = mapped_column(
        String(100),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )


# =========================================================
# OUTBOX
# =========================================================

class Outbox(Base):
    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(
        primary_key=True,
    )

    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger,
    )

    text: Mapped[str] = mapped_column(
        Text,
    )

    attempts: Mapped[int] = mapped_column(
        default=0,
    )

    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        index=True,
    )

    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    last_error: Mapped[str | None] = mapped_column(
        String(100),
    )


# =========================================================
# REALTIME EVENTS
# =========================================================

class RealtimeEvent(Base):
    __tablename__ = "realtime_events"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id"),
        index=True,
    )

    kind: Mapped[str] = mapped_column(
        String(30),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )


# =========================================================
# SYSTEM SETTINGS
# =========================================================

class SystemSettings(Base):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        default=1,
    )

    organization_name: Mapped[str] = mapped_column(
        String(200),
        default="Qala Gas",
    )

    contact_phone: Mapped[str] = mapped_column(
        String(40),
        default="",
    )

    emergency_phone: Mapped[str] = mapped_column(
        String(40),
        default="",
    )

    max_photo_mb: Mapped[int] = mapped_column(
        default=10,
    )

    notification_texts: Mapped[dict] = mapped_column(
        JSON,
        default=lambda: {
            "IN_PROGRESS": "🟡 {number} өтініміңіз өңдеуге алынды.",
            "COMPLETED": "✅ {number} өтініміңіз орындалды.",
            "REJECTED": "❌ {number} өтініміңіз қабылданбады.",
        },
    )


# =========================================================
# MONITORING & SECURITY
# =========================================================

class SecuritySeverity(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    source: Mapped[str] = mapped_column(
        String(30),
        index=True,
    )

    severity: Mapped[SecuritySeverity] = mapped_column(
        enum_col(
            SecuritySeverity,
            "security_severity",
        ),
        default=SecuritySeverity.INFO,
        index=True,
    )

    signature: Mapped[str | None] = mapped_column(
        String(500),
    )

    src_ip: Mapped[str | None] = mapped_column(
        String(45),
        index=True,
    )

    src_country: Mapped[str | None] = mapped_column(
        String(100),
    )

    dst_port: Mapped[int | None] = mapped_column(
        Integer,
    )

    action: Mapped[str | None] = mapped_column(
        String(50),
    )

    raw: Mapped[dict | None] = mapped_column(
        JSON,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        index=True,
    )


class BlockedIP(Base):
    __tablename__ = "blocked_ips"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    ip: Mapped[str] = mapped_column(
        String(45),
        unique=True,
        index=True,
    )

    reason: Mapped[str | None] = mapped_column(
        String(500),
    )

    source: Mapped[str] = mapped_column(
        String(50),
        default="manual",
    )

    blocked_by: Mapped[int | None] = mapped_column(
        ForeignKey("admins.id"),
        index=True,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        index=True,
    )


class AlertStatus(str, enum.Enum):
    OPEN = "OPEN"
    ACK = "ACK"
    RESOLVED = "RESOLVED"


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    type: Mapped[str] = mapped_column(
        String(100),
        index=True,
    )

    severity: Mapped[SecuritySeverity] = mapped_column(
        enum_col(
            SecuritySeverity,
            "alert_severity",
        ),
        default=SecuritySeverity.WARNING,
        index=True,
    )

    message: Mapped[str] = mapped_column(
        Text,
    )

    status: Mapped[AlertStatus] = mapped_column(
        enum_col(
            AlertStatus,
            "alert_status",
        ),
        default=AlertStatus.OPEN,
        index=True,
    )

    acknowledged_by: Mapped[int | None] = mapped_column(
        ForeignKey("admins.id"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        index=True,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    # =========================================================
# API KEYS
# =========================================================

class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    name: Mapped[str] = mapped_column(
        String(200),
    )

    key_prefix: Mapped[str] = mapped_column(
        String(20),
        index=True,
    )

    key_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
    )

    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("admins.id"),
        index=True,
    )

    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        index=True,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )

    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        index=True,
    )
