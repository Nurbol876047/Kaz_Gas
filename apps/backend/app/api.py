import asyncio
import csv
import hashlib
import io
import json
import secrets
from datetime import date
from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from openpyxl import Workbook
from sqlalchemy import case, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool
from app.auth import (
    DUMMY_HASH,
    bot_auth,
    check_origin,
    create_session,
    current_admin,
    managers,
    password_hasher,
    rate_limit,
    redis,
    super_admin,
)
from app.config import get_settings
from app.database import Session, get_db, utcnow
from app.ddos_monitor import DDoSMetrics, detect_ddos
from app.models import (
    Admin,
    AdminSession,
    AlertStatus,
    Application,
    ApplicationFile,
    ApplicationHistory,
    ApplicationType,
    AuditLog,
    FileType,
    Outbox,
    Priority,
    RealtimeEvent,
    Role,
    SecuritySeverity,
    Status,
    User,
)
from app.repositories import (
    application_dict,
    apply_filters,
    create_api_key,
    delete_api_key,
    get_api_keys,
    get_alerts,
    get_application,
    get_blocked_ips,
    get_security_events,
    scoped_query,
)
from app.schemas import (
    AlertResponse,
    AlertUpdate,
    ApiKeyCreate,
    ApiKeyCreatedResponse,
    ApiKeyResponse,
    ApplicationUpdate,
    Assignment,
    BlockIPCreate,
    BlockedIPResponse,
    Comment,
    CreateAdmin,
    CreateApplication,
    Login,
    SecurityEventResponse,
    SettingsUpdate,
    StatusUpdate,
    UpdateAdmin,
)
from app.services import (
    assign_application,
    audit,
    block_ip,
    change_alert_status,
    change_status,
    check_version,
    create_application,
    event,
    settings_row,
    unblock_ip,
)
from app.storage import save_photo, storage_path

router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]
Actor = Annotated[Admin, Depends(current_admin)]
Manager = Annotated[Admin, Depends(managers)]
Super = Annotated[Admin, Depends(super_admin)]
internal = APIRouter(prefix="/internal", dependencies=[Depends(bot_auth)])


def admin_dict(admin):
    return {"id": admin.id, "name": admin.name, "email": admin.email, "role": admin.role, "active": admin.active}


@router.get("/health/live")
async def live():
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(db: DB):
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            503,
            f"Database unavailable: {type(exc).__name__}",
        ) from exc

    try:
        await redis.ping()
    except Exception as exc:
        raise HTTPException(
            503,
            f"Redis unavailable: {type(exc).__name__}",
        ) from exc

    try:
        await settings_row(db)
    except Exception as exc:
        raise HTTPException(
            503,
            f"Settings unavailable: {type(exc).__name__}",
        ) from exc

    return {"status": "ready"}


@router.post("/auth/login")
async def login(data: Login, request: Request, response: Response, db: DB):
    check_origin(request)
    email = str(data.email).lower()
    await rate_limit(f"login-ip:{request.client.host}", 20, 900)
    await rate_limit(f"login-email:{hashlib.sha256(email.encode()).hexdigest()}", 8, 900)
    admin = await db.scalar(select(Admin).where(Admin.email == email))
    valid = await run_in_threadpool(password_hasher.verify, data.password, admin.password_hash if admin else DUMMY_HASH)
    if not valid or admin is None or not admin.active:
        audit(db, None, "login_failed", "auth")
        await db.commit()
        raise HTTPException(401, "Email немесе құпиясөз қате")
    old = request.cookies.get("session")
    if old:
        await db.execute(
            delete(AdminSession).where(AdminSession.token_hash == hashlib.sha256(old.encode()).hexdigest())
        )
    token, csrf = await create_session(db, admin)
    audit(db, admin.id, "login", "auth")
    await db.commit()
    response.set_cookie(
        "session",
        token,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        max_age=get_settings().session_hours * 3600,
        path="/api",
    )
    return {"admin": admin_dict(admin), "csrf_token": csrf}


@router.get("/auth/me")
async def me(request: Request, admin: Actor):
    return {"admin": admin_dict(admin), "csrf_token": request.state.session.csrf_token}


@router.post("/auth/logout", status_code=204)
async def logout(request: Request, response: Response, admin: Actor, db: DB):
    await db.delete(request.state.session)
    audit(db, admin.id, "logout", "auth")
    await db.commit()
    response.delete_cookie("session", path="/api", secure=get_settings().cookie_secure, httponly=True, samesite="lax")


def filters(
    q: str | None = Query(None, max_length=100),
    personal_account: str | None = Query(None, max_length=30),
    application_number: str | None = Query(None, max_length=50),
    application_type: ApplicationType | None = None,
    status: Status | None = None,
    priority: Priority | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    assigned_to: int | None = Query(None, gt=0),
):
    return dict(
        q=q,
        personal_account=personal_account,
        application_number=application_number,
        application_type=application_type,
        status=status,
        priority=priority,
        date_from=date_from,
        date_to=date_to,
        assigned_to=assigned_to,
    )


Filters = Annotated[dict, Depends(filters)]


@router.get("/applications")
async def applications(
    db: DB,
    admin: Actor,
    filters: Filters,
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(20, ge=1, le=100),
    sort: Literal["created_at", "application_number", "status", "priority"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
):
    query = apply_filters(scoped_query(admin), **filters)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    column = getattr(Application, sort)
    if sort == "priority":
        column = case(
            (Application.priority == Priority.CRITICAL, 3), (Application.priority == Priority.HIGH, 2), else_=1
        )
    query = query.order_by(column.desc() if order == "desc" else column.asc(), Application.id.desc())
    rows = (await db.scalars(query.offset((page - 1) * page_size).limit(page_size))).all()
    return {
        "items": [await application_dict(db, a) for a in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/applications/{application_id}")
async def detail(application_id: int, db: DB, admin: Actor):
    return await application_dict(db, await get_application(db, application_id, admin), detail=True)


@router.patch("/applications/{application_id}/status")
async def status(application_id: int, data: StatusUpdate, db: DB, admin: Actor):
    application = await get_application(db, application_id, admin, lock=True)
    await change_status(db, application, admin, data)
    return await application_dict(db, application, detail=True)


@router.patch("/applications/{application_id}/assign")
async def assign(application_id: int, data: Assignment, db: DB, admin: Manager):
    application = await get_application(db, application_id, admin, lock=True)
    await assign_application(db, application, admin, data)
    return await application_dict(db, application, detail=True)


@router.patch("/applications/{application_id}")
async def update(application_id: int, data: ApplicationUpdate, db: DB, admin: Manager):
    application = await get_application(db, application_id, admin, lock=True)
    check_version(application, data.version)
    if application.application_type == ApplicationType.GAS_LEAK and data.priority not in {None, Priority.CRITICAL}:
        raise HTTPException(422, "Газ шығуы — әрқашан CRITICAL")
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    if changes.get("priority", "absent") is None:
        raise HTTPException(422, "Priority cannot be null")
    if not changes:
        raise HTTPException(422, "Өзгерістер жоқ")
    for key, value in changes.items():
        setattr(application, key, value)
    application.version += 1
    application.updated_at = utcnow()
    db.add(
        ApplicationHistory(
            application_id=application.id,
            admin_id=admin.id,
            old_status=application.status,
            new_status=application.status,
            comment=f"Өрістер жаңартылды: {', '.join(changes)}"
            + (f"\n{data.admin_comment}" if data.admin_comment else ""),
        )
    )
    audit(db, admin.id, "application_update", application_id)
    await event(db, application, "updated")
    await db.commit()
    return await application_dict(db, application, detail=True)


@router.post("/applications/{application_id}/comments", status_code=201)
async def comment(application_id: int, data: Comment, db: DB, admin: Actor):
    application = await get_application(db, application_id, admin, lock=True)
    check_version(application, data.version)
    db.add(
        ApplicationHistory(
            application_id=application.id,
            admin_id=admin.id,
            old_status=application.status,
            new_status=application.status,
            comment=data.comment,
            public_comment=data.public_comment,
        )
    )
    application.version += 1
    application.updated_at = utcnow()
    if data.public_comment:
        user = await db.get(User, application.user_id)
        db.add(
            Outbox(telegram_user_id=user.telegram_user_id, text=f"{application.application_number}\n\n{data.comment}")
        )
    audit(db, admin.id, "public_comment" if data.public_comment else "internal_comment", application_id)
    await event(db, application, "updated")
    await db.commit()
    return {"version": application.version}


@router.get("/applications/{application_id}/history")
async def history(application_id: int, db: DB, admin: Actor):
    await get_application(db, application_id, admin)
    rows = (
        await db.execute(
            select(ApplicationHistory, Admin.name)
            .outerjoin(Admin)
            .where(ApplicationHistory.application_id == application_id)
            .order_by(ApplicationHistory.id.desc())
        )
    ).all()
    return [
        {**{c.name: getattr(row, c.name) for c in ApplicationHistory.__table__.columns}, "admin_name": name}
        for row, name in rows
    ]


@router.get("/files/{file_id}")
async def file(file_id: UUID, db: DB, admin: Actor):
    row = await db.get(ApplicationFile, str(file_id))
    if row is None or row.application_id is None:
        raise HTTPException(404, "Фото табылмады")
    await get_application(db, row.application_id, admin)
    path = storage_path(row.storage_url)
    if not path.is_file():
        raise HTTPException(404, "Фото табылмады")
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/admins")
async def admins(db: DB, admin: Actor):
    query = select(Admin).order_by(Admin.name)
    if admin.role == Role.OPERATOR:
        query = query.where(Admin.id == admin.id)
    return [admin_dict(a) for a in (await db.scalars(query)).all()]


@router.post("/admins", status_code=201)
async def add_admin(data: CreateAdmin, db: DB, admin: Super):
    from sqlalchemy.exc import IntegrityError

    new = Admin(
        name=data.name,
        email=str(data.email).lower(),
        role=data.role,
        password_hash=await run_in_threadpool(password_hasher.hash, data.password),
    )
    db.add(new)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "Email тіркелген") from exc
    audit(db, admin.id, "admin_create", new.id)
    await db.commit()
    return admin_dict(new)


@router.patch("/admins/{admin_id}")
async def edit_admin(admin_id: int, data: UpdateAdmin, db: DB, admin: Super):
    # Lock the supervisor set in a stable order to prevent concurrent removal of every supervisor.
    supervisors = (
        await db.scalars(
            select(Admin)
            .where(Admin.role == Role.SUPER_ADMIN)
            .order_by(Admin.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    if not admin.active:
        raise HTTPException(403, "Қолжетімділік тоқтатылды")
    target = await db.get(Admin, admin_id)
    if target is None:
        raise HTTPException(404, "Қызметкер табылмады")
    if target.id == admin.id and not data.active:
        raise HTTPException(422, "Өзіңізді бұғаттай алмайсыз")
    if (
        not data.active
        and target.active
        and target.role == Role.SUPER_ADMIN
        and sum(a.active for a in supervisors) <= 1
    ):
        raise HTTPException(422, "Кемінде бір бас әкімші қажет")
    target.active = data.active
    if not data.active:
        await db.execute(delete(AdminSession).where(AdminSession.admin_id == target.id))
    audit(db, admin.id, "admin_activate" if data.active else "admin_deactivate", target.id)
    await db.commit()
    return admin_dict(target)


@router.get("/settings")
async def settings(db: DB, admin: Actor):
    row = await settings_row(db)
    return {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name != "id"}


@router.patch("/settings")
async def update_settings(data: SettingsUpdate, db: DB, admin: Super):
    row = await settings_row(db)
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    audit(db, admin.id, "settings_update", "system")
    await db.commit()
    return data


@router.get("/application-types")
async def types(admin: Actor):
    return [
        {"value": "METER_NOT_WORKING", "label": "Счетчик жұмыс жасамайды"},
        {"value": "MPI_REMOVAL", "label": "МПИ-ге шешу"},
        {"value": "GAS_LEAK", "label": "Есептеу құралынан газ шығуы"},
    ]


async def stats_for(db, query):
    sub = query.subquery()
    aggregates = [func.count().label("total")]
    aggregates += [func.coalesce(func.sum(case((sub.c.status == s, 1), else_=0)), 0).label(s.value) for s in Status]
    aggregates += [
        func.coalesce(func.sum(case((sub.c.priority == Priority.CRITICAL, 1), else_=0)), 0).label("critical")
    ]
    summary = dict((await db.execute(select(*aggregates).select_from(sub))).mappings().one())
    # Aggregate elapsed time in the DB; avoids loading report datasets into memory.
    if db.bind.dialect.name == "postgresql":
        elapsed = func.extract("epoch", sub.c.completed_at - sub.c.created_at) / 3600
    else:
        elapsed = (func.julianday(sub.c.completed_at) - func.julianday(sub.c.created_at)) * 24
    summary["average_processing_hours"] = await db.scalar(
        select(func.avg(elapsed)).where(sub.c.status == Status.COMPLETED)
    )
    summary["by_type"] = [
        {"type": t, "count": c}
        for t, c in (
            await db.execute(select(sub.c.application_type, func.count()).group_by(sub.c.application_type))
        ).all()
    ]
    # Reporting days use the organization's timezone.
    day_expr = (
        func.date(func.timezone(get_settings().timezone, sub.c.created_at))
        if db.bind.dialect.name == "postgresql"
        else func.date(sub.c.created_at)
    )
    summary["daily"] = [
        {"date": str(d), "count": c}
        for d, c in (
            await db.execute(select(day_expr, func.count()).group_by(day_expr).order_by(day_expr.desc()).limit(30))
        ).all()
    ][::-1]
    return summary


@router.get("/dashboard/stats")
@router.get("/reports")
async def stats(db: DB, admin: Actor, filters: Filters):
    return await stats_for(db, apply_filters(scoped_query(admin), **filters))


def safe_cell(value):
    value = str(value or "")
    return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value


def make_export(rows, format):
    header = ["Нөмір", "Күні", "Дербес шот", "Түрі", "Мәртебе", "Басымдық", "Орындаушы"]
    data = [
        [
            a.application_number,
            a.created_at.isoformat(),
            a.personal_account,
            a.application_type.value,
            a.status.value,
            a.priority.value,
            safe_cell(name),
        ]
        for a, name in rows
    ]
    if format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(header)
        writer.writerows(data)
        return buffer.getvalue().encode("utf-8-sig")
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Өтінімдер")
    sheet.append(header)
    for row in data:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@router.get("/reports/export")
async def export(db: DB, admin: Actor, filters: Filters, format: Literal["csv", "xlsx"] = "csv"):
    await rate_limit(f"export:{admin.id}", 10, 300)
    query = apply_filters(scoped_query(admin), **filters)
    count = await db.scalar(select(func.count()).select_from(query.subquery()))
    if count > 50000:
        raise HTTPException(422, "Экспорт шегі 50 000. Күн аралығын қысқартыңыз.")
    rows = (
        await db.execute(
            query.add_columns(Admin.name)
            .outerjoin(Admin, Application.assigned_to == Admin.id)
            .order_by(Application.created_at.desc())
        )
    ).all()
    result = await run_in_threadpool(make_export, rows, format)
    audit(db, admin.id, "report_export", format)
    await db.commit()
    media = (
        "text/csv; charset=utf-8"
        if format == "csv"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return Response(
        result, media_type=media, headers={"Content-Disposition": f'attachment; filename="applications.{format}"'}
    )


@router.get("/operations")
async def operations(db: DB, admin: Super):
    return {
        "pending_notifications": await db.scalar(
            select(func.count()).select_from(Outbox).where(Outbox.sent_at.is_(None), Outbox.attempts < 12)
        ),
        "failed_notifications": await db.scalar(
            select(func.count()).select_from(Outbox).where(Outbox.sent_at.is_(None), Outbox.attempts >= 12)
        ),
    }


@router.post("/operations/retry-notifications")
async def retry_notifications(db: DB, admin: Super):
    from sqlalchemy import update

    result = await db.execute(
        update(Outbox)
        .where(Outbox.sent_at.is_(None), Outbox.attempts >= 12)
        .values(attempts=0, next_attempt_at=utcnow())
    )
    audit(db, admin.id, "retry_notifications", "outbox")
    await db.commit()
    return {"retried": result.rowcount}


@router.get("/audit")
async def audit_list(db: DB, admin: Super, page: int = Query(1, ge=1)):
    rows = (await db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).offset((page - 1) * 50).limit(50))).all()
    return [{c.name: getattr(row, c.name) for c in AuditLog.__table__.columns} for row in rows]


@router.get("/events")
async def events(request: Request, db: DB, admin: Actor):
    raw = request.headers.get("last-event-id", "")
    if raw and (not raw.isdigit() or len(raw) > 18):
        raise HTTPException(422, "Invalid event cursor")
    cursor = int(raw) if raw else (await db.scalar(select(func.max(RealtimeEvent.id))) or 0)
    session_hash = request.state.session.token_hash
    # End initial read transaction before holding a long SSE connection.
    await db.rollback()

    async def stream():
        nonlocal cursor
        yield "event: ready\ndata: {}\n\n"
        while not await request.is_disconnected():
            async with Session() as stream_db:
                active = await stream_db.scalar(
                    select(Admin)
                    .join(AdminSession)
                    .where(
                        AdminSession.token_hash == session_hash,
                        AdminSession.expires_at > utcnow(),
                        Admin.active.is_(True),
                    )
                )
                if active is None:
                    yield "event: expired\ndata: {}\n\n"
                    return
                query = (
                    select(RealtimeEvent, Application.application_number, Application.priority)
                    .join(Application)
                    .where(RealtimeEvent.id > cursor)
                )
                if active.role == Role.OPERATOR:
                    query = query.where(Application.assigned_to == active.id)
                rows = (await stream_db.execute(query.order_by(RealtimeEvent.id).limit(100))).all()
                for e, number, priority in rows:
                    cursor = e.id
                    payload = json.dumps(
                        {"id": e.application_id, "number": number, "priority": priority, "kind": e.kind}
                    )
                    yield f"id: {cursor}\nevent: application\ndata: {payload}\n\n"
            yield ": heartbeat\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store, no-transform", "X-Accel-Buffering": "no"},
    )


# =========================================================
# SECURITY
# =========================================================


@router.get("/security/events", response_model=list[SecurityEventResponse])
async def security_events(
    db: DB,
    admin: Actor,
    severity: SecuritySeverity | None = None,
    source: str | None = Query(None, max_length=30),
    src_ip: str | None = Query(None, max_length=45),
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(50, ge=1, le=100),
):
    return await get_security_events(
        db,
        severity=severity,
        source=source,
        src_ip=src_ip,
        limit=page_size,
        offset=(page - 1) * page_size,
    )


@router.get("/security/blocked-ips", response_model=list[BlockedIPResponse])
async def blocked_ips(
    db: DB,
    admin: Actor,
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(50, ge=1, le=100),
):
    return await get_blocked_ips(
        db,
        limit=page_size,
        offset=(page - 1) * page_size,
    )


@router.post("/security/blocked-ips", response_model=BlockedIPResponse, status_code=201)
async def add_blocked_ip(
    data: BlockIPCreate,
    db: DB,
    admin: Manager,
):
    return await block_ip(
        db,
        ip=data.ip,
        admin_id=admin.id,
        reason=data.reason,
        expires_at=data.expires_at,
        source="manual",
    )


@router.delete("/security/blocked-ips/{blocked_ip_id}", status_code=204)
async def remove_blocked_ip(
    blocked_ip_id: int,
    db: DB,
    admin: Manager,
):
    await unblock_ip(
        db,
        blocked_ip_id=blocked_ip_id,
        admin_id=admin.id,
    )
    return Response(status_code=204)


@router.get("/alerts", response_model=list[AlertResponse])
async def alerts(
    db: DB,
    admin: Actor,
    status: AlertStatus | None = None,
    severity: SecuritySeverity | None = None,
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(50, ge=1, le=100),
):
    return await get_alerts(
        db,
        status=status,
        severity=severity,
        limit=page_size,
        offset=(page - 1) * page_size,
    )


@router.patch("/alerts/{alert_id}", response_model=AlertResponse)
async def update_alert(
    alert_id: int,
    data: AlertUpdate,
    db: DB,
    admin: Manager,
):
    return await change_alert_status(
        db,
        alert_id=alert_id,
        status=data.status,
        admin_id=admin.id,
    )


@internal.get("/settings")
async def bot_settings(db: DB):
    row = await settings_row(db)
    return {
        "organization_name": row.organization_name,
        "contact_phone": row.contact_phone,
        "emergency_phone": row.emergency_phone,
        "max_photo_mb": row.max_photo_mb,
    }


@internal.post("/photos", status_code=201)
async def upload_photo(
    db: DB,
    telegram_user_id: int = Form(gt=0, le=2**52),
    telegram_file_id: str = Form(max_length=512),
    file_type: FileType = Form(),
    photo: UploadFile = File(),
):
    await rate_limit(f"upload:{telegram_user_id}", 20, 3600)
    if file_type == FileType.OTHER:
        raise HTTPException(422, "Unsupported photo purpose")
    config = await settings_row(db)
    key, content_hash = await save_photo(photo, min(config.max_photo_mb * 1024 * 1024, get_settings().max_photo_bytes))
    row = ApplicationFile(
        owner_telegram_id=telegram_user_id, telegram_file_id=telegram_file_id, file_type=file_type,
        storage_url=key, content_hash=content_hash,
    )
    db.add(row)
    try:
        await db.commit()
    except Exception:
        storage_path(key).unlink(missing_ok=True)
        raise
    return {"id": row.id}


@internal.post("/applications", status_code=201)
async def bot_create(data: CreateApplication, db: DB):
    await rate_limit(f"create:{data.user.telegram_user_id}", 20, 3600)
    application = await create_application(db, data)
    return {"id": application.id, "application_number": application.application_number, "status": application.status}


@internal.get("/users/{telegram_user_id}/applications")
async def bot_applications(telegram_user_id: int, db: DB, page: int = Query(1, ge=1, le=10000)):
    query = select(Application).join(User).where(User.telegram_user_id == telegram_user_id)
    rows = (await db.scalars(query.order_by(Application.id.desc()).offset((page - 1) * 5).limit(6))).all()
    return {
        "items": [
            {
                "id": a.id,
                "application_number": a.application_number,
                "application_type": a.application_type,
                "status": a.status,
                "created_at": a.created_at,
            }
            for a in rows[:5]
        ],
        "has_more": len(rows) > 5,
    }


@internal.get("/users/{telegram_user_id}/applications/{application_id}")
async def bot_detail(telegram_user_id: int, application_id: int, db: DB):
    a = await db.scalar(
        select(Application)
        .join(User)
        .where(User.telegram_user_id == telegram_user_id, Application.id == application_id)
    )
    if not a:
        raise HTTPException(404, "Өтінім табылмады")
    return {
        "application_number": a.application_number,
        "personal_account": a.personal_account,
        "application_type": a.application_type,
        "status": a.status,
        "created_at": a.created_at,
        "requested_date": a.requested_date,
    }

@router.get("/monitoring/health")
async def monitoring_health():
    database_status = "down"
    redis_status = "down"

    try:
        async with Session() as db:
            await db.execute(text("SELECT 1"))
            database_status = "up"
    except Exception:
        database_status = "down"

    try:
        await redis.ping()
        redis_status = "up"
    except Exception:
        redis_status = "down"

    overall_status = (
        "ok"
        if database_status == "up"
        and redis_status == "up"
        else "degraded"
    )

    return {
        "status": overall_status,
        "services": {
            "backend": "up",
            "database": database_status,
            "redis": redis_status,
        },
    }
    
    
@router.get("/monitoring/metrics")
async def monitoring_metrics(
    admin: Actor,
    range: Literal["1h", "6h", "24h", "7d"] = Query(default="1h"),
):
    return {
        "range": range,
        "source": "prometheus",
        "metrics": {
            "requests_per_second": [],
            "error_rate": [],
            "response_time_ms": [],
            "cpu_usage": [],
            "memory_usage": [],
        },
    }


@router.get("/monitoring/ddos")
async def monitoring_ddos(
    admin: Actor,
    current_rps: float = Query(default=0, ge=0),
    average_rps_7d: float = Query(default=0, ge=0),
    syn_recv: int = Query(default=0, ge=0),
    error_rate_429_503: float = Query(default=0, ge=0, le=100),
    inbound_traffic_percent: float = Query(default=0, ge=0, le=100),
    requests_per_ip_minute: int = Query(default=0, ge=0),
    unique_ip_spike_ratio: float = Query(default=0, ge=0),
):
    metrics = DDoSMetrics(
        current_rps=current_rps,
        average_rps_7d=average_rps_7d,
        syn_recv=syn_recv,
        error_rate_429_503=error_rate_429_503,
        inbound_traffic_percent=inbound_traffic_percent,
        requests_per_ip_minute=requests_per_ip_minute,
        unique_ip_spike_ratio=unique_ip_spike_ratio,
    )

    result = detect_ddos(metrics)

    return {
        "status": result.status.value,
        "warning_count": result.warning_count,
        "attack_count": result.attack_count,
        "warning_signals": result.warning_signals,
        "attack_signals": result.attack_signals,
        "metrics": {
            "current_rps": metrics.current_rps,
            "average_rps_7d": metrics.average_rps_7d,
            "syn_recv": metrics.syn_recv,
            "error_rate_429_503": metrics.error_rate_429_503,
            "inbound_traffic_percent": metrics.inbound_traffic_percent,
            "requests_per_ip_minute": metrics.requests_per_ip_minute,
            "unique_ip_spike_ratio": metrics.unique_ip_spike_ratio,
        },
    }

@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    db: DB,
    admin: Actor,
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(50, ge=1, le=100),
):
    return await get_api_keys(
        db,
        limit=page_size,
        offset=(page - 1) * page_size,
    )


@router.post("/api-keys", response_model=ApiKeyCreatedResponse, status_code=201)
async def add_api_key(
    data: ApiKeyCreate,
    db: DB,
    admin: Actor,
):
    raw_key = "ud_" + secrets.token_urlsafe(32)
    key_prefix = raw_key[:12]
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    api_key = await create_api_key(
        db,
        name=data.name,
        key_prefix=key_prefix,
        key_hash=key_hash,
        created_by=admin.id,
        expires_at=data.expires_at,
    )

    await db.commit()
    await db.refresh(api_key)

    return ApiKeyCreatedResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        created_by=api_key.created_by,
        active=api_key.active,
        expires_at=api_key.expires_at,
        last_used_at=api_key.last_used_at,
        created_at=api_key.created_at,
        key=raw_key,
    )


@router.delete("/api-keys/{api_key_id}", status_code=204)
async def remove_api_key(
    api_key_id: int,
    db: DB,
    admin: Actor,
):
    deleted = await delete_api_key(
        db,
        api_key_id=api_key_id,
    )

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="API key not found",
        )

    await db.commit()
    
router.include_router(internal)
