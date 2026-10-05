import asyncio
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.models import Application, Outbox
from app.repositories import get_application
from app.schemas import CreateApplication, StatusUpdate, local_today
from app.services import change_status, create_application
from app.subscriber_models import SubscriberAccount


async def test_postgres_concurrent_submission_is_idempotent(db):
    if db.bind.dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    db.add(SubscriberAccount(account_number="987654321", meter_number="RACE-1", full_name="Synthetic resident",
                             address="Test address", telegram_user_id=321987))
    await db.commit()
    payload = CreateApplication(
        user={"telegram_user_id": 321987, "first_name": "Concurrent"},
        idempotency_key=uuid4(),
        personal_account="987654321",
        application_type="MPI_REMOVAL",
        requested_date=local_today(),
    )

    async def create():
        async with factory() as session:
            return (await create_application(session, payload)).id

    results = await asyncio.gather(*[create() for _ in range(5)])
    assert len(set(results)) == 1
    assert await db.scalar(select(func.count()).select_from(Application)) == 1


async def test_postgres_concurrent_status_has_one_winner(db, admin):
    if db.bind.dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    db.add(SubscriberAccount(account_number="987654321", meter_number="RACE-2", full_name="Synthetic resident",
                             address="Test address", telegram_user_id=321988))
    await db.commit()
    payload = CreateApplication(
        user={"telegram_user_id": 321988, "first_name": "Concurrent"},
        idempotency_key=uuid4(),
        personal_account="987654321",
        application_type="MPI_REMOVAL",
        requested_date=local_today(),
    )
    application = await create_application(db, payload)
    factory = async_sessionmaker(db.bind, expire_on_commit=False)

    async def change(status):
        async with factory() as session:
            try:
                row = await get_application(session, application.id, lock=True)
                await change_status(session, row, admin, StatusUpdate(version=1, status=status))
                return 200
            except HTTPException as error:
                return error.status_code

    assert sorted(await asyncio.gather(change("IN_PROGRESS"), change("REJECTED"))) == [200, 409]
    assert await db.scalar(select(func.count()).select_from(Outbox)) == 1
