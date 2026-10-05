import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import utcnow
from app.models import (
    Admin,
    Alert,
    AlertStatus,
    Application,
    ApplicationFile,
    ApplicationHistory,
    ApplicationType,
    AuditLog,
    BlockedIP,
    FileType,
    Outbox,
    Priority,
    RealtimeEvent,
    SecurityEvent,
    SecuritySeverity,
    Status,
    SystemSettings,
    User,
)
from app.schemas import CreateApplication
from app.subscriber_models import SubscriberAccount


TRANSITIONS = {
    Status.NEW: {
        Status.IN_PROGRESS,
        Status.REJECTED,
    },
    Status.IN_PROGRESS: {
        Status.COMPLETED,
        Status.REJECTED,
    },
    Status.COMPLETED: set(),
    Status.REJECTED: set(),
}


async def settings_row(db):
    row = await db.get(SystemSettings, 1)

    if row is None:
        # The migration seeds this row; tests can create it explicitly.
        raise HTTPException(
            503,
            "System settings missing: run migrations",
        )

    return row


def audit(db, admin_id, action, target):
    db.add(
        AuditLog(
            admin_id=admin_id,
            action=action,
            target=str(target),
        )
    )


async def event(db, application, kind):
    # Serialize event allocation through commit so SSE cursors never skip a late commit.
    if db.bind.dialect.name == "postgresql":
        await db.execute(
            text(
                "SELECT pg_advisory_xact_lock(72727001)"
            )
        )

    db.add(
        RealtimeEvent(
            application_id=application.id,
            kind=kind,
        )
    )


def check_version(application, version):
    if application.version != version:
        raise HTTPException(
            409,
            "Өтінім өзгертілген. Бетті жаңартыңыз.",
        )


# =========================================================
# APPLICATION CREATE
# =========================================================


async def create_application(
    db,
    data: CreateApplication,
):
    subscriber = await db.scalar(select(SubscriberAccount).where(
        SubscriberAccount.account_number == data.personal_account,
        SubscriberAccount.telegram_user_id == data.user.telegram_user_id,
        SubscriberAccount.active.is_(True),
    ).with_for_update())
    if subscriber is None and data.application_type != ApplicationType.GAS_LEAK:
        raise HTTPException(403, "Дербес шот расталмаған. /start арқылы қайта кіріңіз.")
    user = await db.scalar(
        select(User)
        .where(
            User.telegram_user_id
            == data.user.telegram_user_id
        )
        .with_for_update()
    )

    if user is None:
        try:
            async with db.begin_nested():
                user = User(
                    **data.user.model_dump()
                )

                db.add(user)
                await db.flush()

        except IntegrityError:
            user = await db.scalar(
                select(User)
                .where(
                    User.telegram_user_id
                    == data.user.telegram_user_id
                )
                .with_for_update()
            )

    existing = await db.scalar(
        select(Application).where(
            Application.user_id == user.id,
            Application.idempotency_key
            == str(data.idempotency_key),
        )
    )

    if existing:
        return existing

    for key, value in (
        data.user.model_dump().items()
    ):
        setattr(
            user,
            key,
            value,
        )

    requested = [
        (
            data.meter_photo_id,
            FileType.METER_PHOTO,
        ),
        (
            data.leak_photo_id,
            FileType.GAS_LEAK_PHOTO,
        ),
    ]

    files = []

    for file_id, expected_type in requested:
        if file_id is None:
            continue

        file = await db.scalar(
            select(ApplicationFile)
            .where(
                ApplicationFile.id
                == str(file_id)
            )
            .with_for_update()
        )

        if (
            file is None
            or file.owner_telegram_id
            != user.telegram_user_id
            or file.application_id is not None
            or file.file_type != expected_type
        ):
            raise HTTPException(
                422,
                "Фото табылмады немесе рұқсат жоқ",
            )

        created = (
            file.created_at.replace(
                tzinfo=utcnow().tzinfo
            )
            if file.created_at.tzinfo is None
            else file.created_at
        )

        if (
            created
            < utcnow()
            - timedelta(hours=24)
        ):
            raise HTTPException(
                422,
                "Фото мерзімі өткен. Қайта жіберіңіз.",
            )

        files.append(file)

    application = Application(
        subscriber_verified=subscriber is not None,
        user_id=user.id,
        idempotency_key=str(
            data.idempotency_key
        ),
        application_number=(
            f"pending-{uuid.uuid4()}"
        ),
        personal_account=(
            data.personal_account
        ),
        application_type=(
            data.application_type
        ),
        requested_date=(
            data.requested_date
        ),
        latitude=data.latitude,
        longitude=data.longitude,
        priority=(
            Priority.CRITICAL
            if data.application_type
            == ApplicationType.GAS_LEAK
            else Priority.NORMAL
        ),
    )

    db.add(application)
    await db.flush()

    day = (
        application.created_at
        .astimezone(
            ZoneInfo(
                get_settings().timezone
            )
        )
        .strftime("%Y%m%d")
    )

    application.application_number = (
        f"REQ-{day}-{application.id:05d}"
    )

    for file in files:
        file.application_id = (
            application.id
        )

    db.add(
        ApplicationHistory(
            application_id=application.id,
            new_status=Status.NEW,
            comment="Өтінім қабылданды",
        )
    )

    await event(
        db,
        application,
        "created",
    )

    await db.commit()

    return application


# =========================================================
# STATUS
# =========================================================


async def change_status(
    db,
    application,
    admin,
    data,
):
    check_version(
        application,
        data.version,
    )

    if (
        data.status
        not in TRANSITIONS[
            application.status
        ]
    ):
        raise HTTPException(
            422,
            "Бұл мәртебеге өтуге болмайды",
        )

    old = application.status

    application.status = data.status
    application.version += 1
    application.updated_at = utcnow()

    if data.status in {
        Status.COMPLETED,
        Status.REJECTED,
    }:
        application.completed_at = (
            utcnow()
        )

    db.add(
        ApplicationHistory(
            application_id=(
                application.id
            ),
            admin_id=admin.id,
            old_status=old,
            new_status=data.status,
            comment=data.comment,
            public_comment=(
                data.public_comment
            ),
        )
    )

    config = await settings_row(db)

    notification_text = (
        config.notification_texts[
            data.status.value
        ].format(
            number=(
                application.application_number
            )
        )
    )

    if (
        data.public_comment
        and data.comment
    ):
        notification_text += (
            f"\n\n{data.comment}"
        )

    user = await db.get(
        User,
        application.user_id,
    )

    db.add(
        Outbox(
            telegram_user_id=(
                user.telegram_user_id
            ),
            text=notification_text,
        )
    )

    audit(
        db,
        admin.id,
        (
            f"status:{old.value}"
            f"->{data.status.value}"
        ),
        application.id,
    )

    await event(
        db,
        application,
        "updated",
    )

    await db.commit()


# =========================================================
# ASSIGN APPLICATION
# =========================================================


async def assign_application(
    db,
    application,
    admin,
    data,
):
    check_version(
        application,
        data.version,
    )

    assignee = (
        await db.get(
            Admin,
            data.assigned_to,
        )
        if data.assigned_to
        else None
    )

    if (
        data.assigned_to
        and (
            assignee is None
            or not assignee.active
        )
    ):
        raise HTTPException(
            422,
            "Белсенді қызметкерді таңдаңыз",
        )

    previous = application.assigned_to

    application.assigned_to = (
        data.assigned_to
    )

    application.version += 1
    application.updated_at = utcnow()

    db.add(
        ApplicationHistory(
            application_id=(
                application.id
            ),
            admin_id=admin.id,
            old_status=(
                application.status
            ),
            new_status=(
                application.status
            ),
            comment=(
                f"Орындаушы: "
                f"{previous or '—'} → "
                f"{assignee.name if assignee else '—'}"
            ),
        )
    )

    audit(
        db,
        admin.id,
        "assign",
        application.id,
    )

    await event(
        db,
        application,
        "updated",
    )

    await db.commit()


# =========================================================
# SECURITY SERVICES
# =========================================================


async def register_security_event(
    db,
    source: str,
    severity: SecuritySeverity,
    signature: str | None = None,
    src_ip: str | None = None,
    src_country: str | None = None,
    dst_port: int | None = None,
    action: str | None = None,
    raw: dict | None = None,
):
    security_event = SecurityEvent(
        source=source,
        severity=severity,
        signature=signature,
        src_ip=src_ip,
        src_country=src_country,
        dst_port=dst_port,
        action=action,
        raw=raw,
    )

    db.add(security_event)

    await db.commit()

    await db.refresh(
        security_event
    )

    return security_event


# =========================================================
# BLOCK IP
# =========================================================


async def block_ip(
    db,
    ip: str,
    admin_id: int | None,
    reason: str | None = None,
    expires_at=None,
    source: str = "manual",
):
    existing = await db.scalar(
        select(BlockedIP).where(
            BlockedIP.ip == ip
        )
    )

    if existing is not None:
        raise HTTPException(
            409,
            "Бұл IP бұрыннан бұғатталған",
        )

    blocked_ip = BlockedIP(
        ip=ip,
        reason=reason,
        source=source,
        blocked_by=admin_id,
        expires_at=expires_at,
    )

    db.add(blocked_ip)

    audit(
        db,
        admin_id,
        "security:block_ip",
        ip,
    )

    await db.commit()

    await db.refresh(
        blocked_ip
    )

    return blocked_ip


async def unblock_ip(
    db,
    blocked_ip_id: int,
    admin_id: int | None,
):
    blocked_ip = await db.get(
        BlockedIP,
        blocked_ip_id,
    )

    if blocked_ip is None:
        raise HTTPException(
            404,
            "Бұғатталған IP табылмады",
        )

    ip = blocked_ip.ip

    await db.delete(
        blocked_ip
    )

    audit(
        db,
        admin_id,
        "security:unblock_ip",
        ip,
    )

    await db.commit()

    return {
        "ok": True,
        "ip": ip,
    }


# =========================================================
# SECURITY ALERTS
# =========================================================


async def create_security_alert(
    db,
    alert_type: str,
    severity: SecuritySeverity,
    message: str,
):
    alert = Alert(
        type=alert_type,
        severity=severity,
        message=message,
        status=AlertStatus.OPEN,
    )

    db.add(alert)

    await db.commit()

    await db.refresh(
        alert
    )

    return alert


async def change_alert_status(
    db,
    alert_id: int,
    status: AlertStatus,
    admin_id: int | None,
):
    alert = await db.get(
        Alert,
        alert_id,
    )

    if alert is None:
        raise HTTPException(
            404,
            "Alert табылмады",
        )

    alert.status = status

    if status == AlertStatus.ACK:
        alert.acknowledged_by = (
            admin_id
        )

    elif status == AlertStatus.RESOLVED:
        alert.acknowledged_by = (
            admin_id
        )

        alert.resolved_at = (
            utcnow()
        )

    elif status == AlertStatus.OPEN:
        alert.acknowledged_by = None
        alert.resolved_at = None

    audit(
        db,
        admin_id,
        (
            f"security:alert:"
            f"{status.value}"
        ),
        alert.id,
    )

    await db.commit()

    await db.refresh(
        alert
    )

    return alert
