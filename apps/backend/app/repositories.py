from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (ApiKey,
    Admin,
    Alert,
    AlertStatus,
    Application,
    ApplicationFile,
    BlockedIP,
    Role,
    SecurityEvent,
    SecuritySeverity,
    User,
)


# =========================================================
# APPLICATIONS
# =========================================================


def scoped_query(admin):
    query = select(Application)

    if admin.role == Role.OPERATOR:
        query = query.where(
            Application.assigned_to == admin.id
        )

    return query


async def get_application(
    db,
    application_id,
    admin=None,
    lock=False,
):
    query = (
        scoped_query(admin)
        if admin
        else select(Application)
    )

    query = query.where(
        Application.id == application_id
    )

    if lock:
        query = query.with_for_update()

    application = await db.scalar(query)

    if application is None:
        raise HTTPException(
            404,
            "Өтінім табылмады",
        )

    return application


def apply_filters(
    query,
    q=None,
    personal_account=None,
    application_number=None,
    application_type=None,
    status=None,
    priority=None,
    date_from: date | None = None,
    date_to: date | None = None,
    assigned_to=None,
):
    if (
        date_from
        and date_to
        and date_from > date_to
    ):
        raise HTTPException(
            422,
            "Күн аралығы дұрыс емес",
        )

    if q:
        term = (
            q.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )

        query = query.where(
            or_(
                Application.application_number.ilike(
                    f"%{term}%",
                    escape="\\",
                ),
                Application.personal_account.ilike(
                    f"%{term}%",
                    escape="\\",
                ),
            )
        )

    for column, value in [
        (
            Application.personal_account,
            personal_account,
        ),
        (
            Application.application_number,
            application_number,
        ),
        (
            Application.application_type,
            application_type,
        ),
        (
            Application.status,
            status,
        ),
        (
            Application.priority,
            priority,
        ),
        (
            Application.assigned_to,
            assigned_to,
        ),
    ]:
        if value is not None:
            query = query.where(
                column == value
            )

    tz = ZoneInfo(
        get_settings().timezone
    )

    if date_from:
        query = query.where(
            Application.created_at
            >= datetime.combine(
                date_from,
                time.min,
                tzinfo=tz,
            )
        )

    if date_to:
        query = query.where(
            Application.created_at
            < datetime.combine(
                date_to + timedelta(days=1),
                time.min,
                tzinfo=tz,
            )
        )

    return query


async def application_dict(
    db,
    application,
    detail=False,
):
    result = {
        c.name: getattr(
            application,
            c.name,
        )
        for c in Application.__table__.columns
        if c.name != "idempotency_key"
    }

    user = await db.get(
        User,
        application.user_id,
    )

    assigned = (
        await db.get(
            Admin,
            application.assigned_to,
        )
        if application.assigned_to
        else None
    )

    result["user"] = {
        "telegram_user_id": user.telegram_user_id,
        "telegram_username": user.telegram_username,
        "first_name": user.first_name,
        "last_name": user.last_name,
    }

    result["assignee_name"] = (
        assigned.name
        if assigned
        else None
    )

    if detail:
        files = (
            await db.scalars(
                select(
                    ApplicationFile
                ).where(
                    ApplicationFile.application_id
                    == application.id
                )
            )
        ).all()

        result["files"] = [
            {
                "id": f.id,
                "file_type": f.file_type,
                "url": f"/api/files/{f.id}",
            }
            for f in files
        ]

        result["subscriber_verified"] = application.subscriber_verified

    return result


# =========================================================
# SECURITY EVENTS
# =========================================================


async def create_security_event(
    db,
    *,
    source: str,
    severity: SecuritySeverity,
    signature: str | None = None,
    src_ip: str | None = None,
    src_country: str | None = None,
    dst_port: int | None = None,
    action: str | None = None,
    raw: dict | None = None,
):
    event = SecurityEvent(
        source=source,
        severity=severity,
        signature=signature,
        src_ip=src_ip,
        src_country=src_country,
        dst_port=dst_port,
        action=action,
        raw=raw,
    )

    db.add(event)

    await db.flush()
    await db.refresh(event)

    return event


async def get_security_events(
    db,
    *,
    severity: SecuritySeverity | None = None,
    source: str | None = None,
    src_ip: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    limit = max(
        1,
        min(limit, 500),
    )

    offset = max(
        0,
        offset,
    )

    query = select(
        SecurityEvent
    )

    if severity is not None:
        query = query.where(
            SecurityEvent.severity
            == severity
        )

    if source is not None:
        query = query.where(
            SecurityEvent.source
            == source
        )

    if src_ip is not None:
        query = query.where(
            SecurityEvent.src_ip
            == src_ip
        )

    query = (
        query
        .order_by(
            SecurityEvent.created_at.desc()
        )
        .offset(offset)
        .limit(limit)
    )

    result = await db.scalars(
        query
    )

    return result.all()


async def get_security_event(
    db,
    event_id: int,
):
    event = await db.get(
        SecurityEvent,
        event_id,
    )

    if event is None:
        raise HTTPException(
            404,
            "Қауіпсіздік оқиғасы табылмады",
        )

    return event


# =========================================================
# BLOCKED IP
# =========================================================


async def create_blocked_ip(
    db,
    *,
    ip: str,
    reason: str | None,
    blocked_by: int | None,
    expires_at: datetime | None = None,
    source: str = "manual",
):
    existing = await db.scalar(
        select(
            BlockedIP
        ).where(
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
        blocked_by=blocked_by,
        expires_at=expires_at,
    )

    db.add(
        blocked_ip
    )

    await db.flush()
    await db.refresh(
        blocked_ip
    )

    return blocked_ip


async def get_blocked_ips(
    db,
    *,
    limit: int = 100,
    offset: int = 0,
):
    limit = max(
        1,
        min(limit, 500),
    )

    offset = max(
        0,
        offset,
    )

    query = (
        select(BlockedIP)
        .order_by(
            BlockedIP.created_at.desc()
        )
        .offset(offset)
        .limit(limit)
    )

    result = await db.scalars(
        query
    )

    return result.all()


async def get_blocked_ip(
    db,
    blocked_ip_id: int,
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

    return blocked_ip


async def delete_blocked_ip(
    db,
    blocked_ip_id: int,
):
    blocked_ip = await get_blocked_ip(
        db,
        blocked_ip_id,
    )

    await db.delete(
        blocked_ip
    )

    await db.flush()

    return blocked_ip


# =========================================================
# ALERTS
# =========================================================


async def create_alert(
    db,
    *,
    type: str,
    severity: SecuritySeverity,
    message: str,
):
    alert = Alert(
        type=type,
        severity=severity,
        message=message,
        status=AlertStatus.OPEN,
    )

    db.add(
        alert
    )

    await db.flush()
    await db.refresh(
        alert
    )

    return alert


async def get_alerts(
    db,
    *,
    status: AlertStatus | None = None,
    severity: SecuritySeverity | None = None,
    limit: int = 100,
    offset: int = 0,
):
    limit = max(
        1,
        min(limit, 500),
    )

    offset = max(
        0,
        offset,
    )

    query = select(
        Alert
    )

    if status is not None:
        query = query.where(
            Alert.status == status
        )

    if severity is not None:
        query = query.where(
            Alert.severity == severity
        )

    query = (
        query
        .order_by(
            Alert.created_at.desc()
        )
        .offset(offset)
        .limit(limit)
    )

    result = await db.scalars(
        query
    )

    return result.all()


async def get_alert(
    db,
    alert_id: int,
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

    return alert


async def update_alert_status(
    db,
    alert_id: int,
    status: AlertStatus,
    admin_id: int | None = None,
):
    alert = await get_alert(
        db,
        alert_id,
    )

    alert.status = status

    if status == AlertStatus.ACK:
        alert.acknowledged_by = (
            admin_id
        )

    elif status == AlertStatus.RESOLVED:
        alert.resolved_at = (
            datetime.now(
                ZoneInfo(
                    get_settings().timezone
                )
            )
        )

        if admin_id is not None:
            alert.acknowledged_by = (
                admin_id
            )

    elif status == AlertStatus.OPEN:
        alert.acknowledged_by = None
        alert.resolved_at = None

    await db.flush()
    await db.refresh(
        alert
    )

    return alert

      

async def get_api_keys(
    db: AsyncSession,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[ApiKey]:
    result = await db.scalars(
        select(ApiKey)
        .order_by(ApiKey.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.all())





async def create_api_key(
    db: AsyncSession,
    *,
    name: str,
    key_prefix: str,
    key_hash: str,
    created_by: int | None,
    expires_at: datetime | None = None,
) -> ApiKey:
    api_key = ApiKey(
        name=name,
        key_prefix=key_prefix,
        key_hash=key_hash,
        created_by=created_by,
        active=True,
        expires_at=expires_at,
    )

    db.add(api_key)
    await db.flush()
    await db.refresh(api_key)

    return api_key


async def delete_api_key(
    db: AsyncSession,
    *,
    api_key_id: int,
) -> bool:
    api_key = await db.get(ApiKey, api_key_id)

    if api_key is None:
        return False

    await db.delete(api_key)
    await db.flush()

    return True
