import os
from unittest.mock import AsyncMock
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.engine import make_url

os.environ.setdefault("BOT_API_KEY", "test-only-service-key-" + "x" * 32)
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("ALLOWED_ORIGINS", "http://test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Admin, Role, SystemSettings  # noqa: E402
from app.auth import password_hasher  # noqa: E402
from app.subscriber_models import SubscriberAccount  # noqa: E402


@pytest.fixture
async def db():
    # TEST_DATABASE_URL must reference a dedicated disposable PostgreSQL DB.
    url = os.getenv("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    if "postgresql" in url and not any(label in (make_url(url).database or "") for label in ["test", "e2e"]):
        raise RuntimeError("Refusing schema reset: test database name must contain test or e2e")
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(SystemSettings(id=1))
        session.add(SubscriberAccount(account_number="12345678", meter_number="TEST-METER-1", full_name="Test resident",
                                      address="Test address", telegram_user_id=123456))
        await session.commit()
        yield session
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def admin(db):
    admin = Admin(
        name="Test Admin",
        email="admin@example.com",
        password_hash=password_hasher.hash("correct-password-123"),
        role=Role.SUPER_ADMIN,
    )
    db.add(admin)
    await db.commit()
    return admin


@pytest.fixture
async def client(db, monkeypatch):
    async def override():
        yield db

    app.dependency_overrides[get_db] = override
    monkeypatch.setattr("app.auth.rate_limit", AsyncMock())
    monkeypatch.setattr("app.api.rate_limit", AsyncMock())
    monkeypatch.setattr("app.subscribers.rate_limit", AsyncMock())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers={"Origin": "http://test"}
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def logged_in(client, admin):
    response = await client.post("/api/auth/login", json={"email": admin.email, "password": "correct-password-123"})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client
