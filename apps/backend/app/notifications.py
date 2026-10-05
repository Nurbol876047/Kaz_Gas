"""Durable, at-least-once Telegram delivery. Run `python -m app.notifications`."""

import asyncio
import logging
from datetime import timedelta
import httpx
from sqlalchemy import delete, or_, select
from app.config import get_settings
from app.database import Session, utcnow
from app.models import AdminSession, ApplicationFile, Outbox
from app.schemas import local_today
from app.storage import storage_path
from app.subscriber_models import MeterReading, SubscriberAccount

log = logging.getLogger("notifications")


async def deliver_one(db, client):
    row = await db.scalar(
        select(Outbox)
        .where(Outbox.sent_at.is_(None), Outbox.attempts < 12, Outbox.next_attempt_at <= utcnow())
        .order_by(Outbox.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if row is None:
        return False
    row.attempts += 1
    try:
        response = await client.post(
            f"https://api.telegram.org/bot{get_settings().bot_token}/sendMessage",
            json={"chat_id": row.telegram_user_id, "text": row.text},
        )
        payload = response.json()
        if response.status_code == 200 and payload.get("ok"):
            row.sent_at = utcnow()
            row.last_error = None
        else:
            # Never persist response text / URL: they may contain tokens or resident data.
            row.last_error = f"telegram_http_{response.status_code}"
            delay = min(3600, max(2**row.attempts, int(payload.get("parameters", {}).get("retry_after", 0))))
            row.next_attempt_at = utcnow() + timedelta(seconds=delay)
            if response.status_code in {400, 403}:
                row.attempts = 12
    except (httpx.HTTPError, ValueError, TypeError):
        row.last_error = "telegram_transport_error"
        row.next_attempt_at = utcnow() + timedelta(seconds=min(3600, 2**row.attempts))
    await db.commit()
    return True


async def send_reminders(db):
    """At most one reminder per subscriber per calendar month, skipped once a report is in."""
    period = local_today().replace(day=1)
    accounts = (
        await db.scalars(
            select(SubscriberAccount)
            .where(
                SubscriberAccount.active.is_(True),
                SubscriberAccount.telegram_user_id.isnot(None),
                or_(SubscriberAccount.last_period.is_(None), SubscriberAccount.last_period < period),
                or_(
                    SubscriberAccount.last_reminder_period.is_(None),
                    SubscriberAccount.last_reminder_period < period,
                ),
            )
            .with_for_update(skip_locked=True)
        )
    ).all()
    for account in accounts:
        pending = await db.scalar(
            select(MeterReading.id).where(
                MeterReading.account_id == account.id,
                MeterReading.period == period,
                MeterReading.status == "PENDING",
            )
        )
        if not pending:
            db.add(
                Outbox(
                    telegram_user_id=account.telegram_user_id,
                    text=(
                        f"{local_today():%d.%m.%Y} күнінде еске саламыз: {account.account_number} дербес шоты "
                        f"бойынша {period:%m.%Y} айының газ есептегіш көрсеткішін жіберу уақыты келді. Ботта "
                        "«📊 Газ көрсеткішін жіберу» бөлімінен есептегіштің фотосын жіберіңіз."
                    ),
                )
            )
        account.last_reminder_period = period
    await db.commit()


async def cleanup(db):
    expired = (
        await db.scalars(
            select(ApplicationFile)
            .where(
                ApplicationFile.application_id.is_(None), ApplicationFile.created_at < utcnow() - timedelta(hours=24)
            )
            .with_for_update(skip_locked=True)
        )
    ).all()
    for file in expired:
        storage_path(file.storage_url).unlink(missing_ok=True)
        await db.delete(file)
    await db.execute(delete(AdminSession).where(AdminSession.expires_at < utcnow()))
    await db.commit()


async def main():
    if not get_settings().bot_token:
        raise RuntimeError("BOT_TOKEN required for notification worker")
    logging.basicConfig(level=logging.INFO)
    ticks = 0
    async with httpx.AsyncClient(timeout=15) as client:
        while True:
            try:
                async with Session() as db:
                    worked = await deliver_one(db, client)
                ticks += 1
                if ticks % 300 == 0:
                    async with Session() as db:
                        await cleanup(db)
                    async with Session() as db:
                        await send_reminders(db)
                if not worked:
                    await asyncio.sleep(2)
            except Exception:
                log.error("Notification worker iteration failed; retrying")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
