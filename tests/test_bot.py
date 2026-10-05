from datetime import datetime, timezone
from unittest.mock import AsyncMock
import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.methods import SendMessage
from aiogram.types import CallbackQuery, Chat, Location, Message, PhotoSize, Update, User
from bot.handlers import router, today, valid_date
from bot.services import APIError, BoundedBuffer
from bot.states import Flow

dispatcher = Dispatcher(storage=MemoryStorage())
dispatcher.include_router(router)


class TelegramSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.messages = []
        self.counter = 100

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, SendMessage):
            self.counter += 1
            message = Message(
                message_id=self.counter,
                date=datetime.now(timezone.utc),
                chat=Chat(id=123456, type="private"),
                text=method.text,
                reply_markup=method.reply_markup
                if method.reply_markup and hasattr(method.reply_markup, "inline_keyboard")
                else None,
            )
            self.messages.append(message)
            return message
        return True

    async def stream_content(self, url, **kwargs):
        yield b""


class Harness:
    def __init__(self):
        self.session = TelegramSession()
        self.bot = Bot("123456:TEST_FAKE_TOKEN_NEVER_CONNECT", session=self.session)
        self.api = AsyncMock()
        async def account_lookup(user_id, identifier, kind="account"):
            return {"verified": True, "account": {"id": 1, "account_number": identifier, "meter_number": "TEST-1",
                     "full_name": "Test resident", "address": "Test address"}}
        self.api.account.side_effect = account_lookup
        self.api.settings.return_value = {"emergency_phone": "", "max_photo_mb": 10}
        self.api.upload.side_effect = [
            {"id": "11111111-1111-4111-8111-111111111111"},
            {"id": "22222222-2222-4222-8222-222222222222"},
        ]
        self.api.create.return_value = {"application_number": "REQ-20260915-00001"}
        self.user = User(id=123456, is_bot=False, first_name="Test")
        self.context = FSMContext(
            dispatcher.storage, StorageKey(bot_id=self.bot.id, chat_id=self.user.id, user_id=self.user.id)
        )
        self.counter = 0

    async def message(self, text=None, **kwargs):
        self.counter += 1
        message = Message(
            message_id=self.counter,
            from_user=self.user,
            chat=Chat(id=self.user.id, type="private"),
            date=datetime.now(timezone.utc),
            text=text,
            **kwargs,
        )
        await dispatcher.feed_update(
            self.bot, Update(update_id=self.counter, message=message), backend=self.api, timezone="Asia/Qyzylorda"
        )

    async def click(self, data, message_id=None):
        self.counter += 1
        message = self.session.messages[-1]
        if message_id:
            message = message.model_copy(update={"message_id": message_id})
        await dispatcher.feed_update(
            self.bot,
            Update(
                update_id=self.counter,
                callback_query=CallbackQuery(
                    id=str(self.counter), from_user=self.user, chat_instance="test", data=data, message=message
                ),
            ),
            backend=self.api,
            timezone="Asia/Qyzylorda",
        )

    async def start_type(self, kind):
        await self.message("/start", entities=[{"type": "bot_command", "offset": 0, "length": 6}])
        await self.message("12345678")
        assert await self.context.get_state() == Flow.CONFIRM_ACCOUNT.state
        await self.click("account:yes")
        await self.click("type:" + kind)


@pytest.fixture
async def h():
    harness = Harness()
    await harness.context.clear()
    yield harness
    await harness.context.clear()
    await harness.bot.session.close()


async def test_account_confirmation_edit_and_cancel(h):
    await h.message("/start", entities=[{"type": "bot_command", "offset": 0, "length": 6}])
    await h.message("not-account")
    assert await h.context.get_state() == Flow.WAITING_ACCOUNT.state
    await h.message("12345678")
    await h.click("account:edit")
    assert await h.context.get_state() == Flow.WAITING_ACCOUNT.state
    await h.message("87654321")
    assert (await h.context.get_data())["personal_account"] == "87654321"
    await h.click("cancel")
    assert await h.context.get_state() is None
    h.api.create.assert_not_awaited()


async def test_meter_fsm_requires_photo_and_location_then_confirm(h):
    await h.start_type("METER_NOT_WORKING")
    await h.message("skip photo")
    assert await h.context.get_state() == Flow.METER_WAITING_PHOTO.state
    await h.message(photo=[PhotoSize(file_id="photo", file_unique_id="unique", width=20, height=20)])
    await h.message("skip location")
    assert await h.context.get_state() == Flow.METER_WAITING_LOCATION.state
    await h.message(location=Location(latitude=0, longitude=0))
    h.api.create.assert_not_awaited()
    assert await h.context.get_state() == Flow.METER_CONFIRM.state
    await h.click("submit")
    h.api.create.assert_awaited_once()
    assert h.api.create.call_args.args[0]["latitude"] == 0
    assert await h.context.get_state() is None


async def test_gas_warning_two_distinct_photos_and_back(h):
    await h.start_type("GAS_LEAK")
    assert any("авариялық газ қызметіне дереу" in m.text for m in h.session.messages)
    await h.message(photo=[PhotoSize(file_id="meter", file_unique_id="same", width=20, height=20)])
    assert await h.context.get_state() == Flow.GAS_WAITING_LEAK_PHOTO.state
    await h.message(photo=[PhotoSize(file_id="meter", file_unique_id="same", width=20, height=20)])
    assert await h.context.get_state() == Flow.GAS_WAITING_LEAK_PHOTO.state
    await h.message(photo=[PhotoSize(file_id="leak", file_unique_id="different", width=20, height=20)])
    await h.message(location=Location(latitude=45, longitude=65))
    await h.click("back")
    assert await h.context.get_state() == Flow.GAS_WAITING_LOCATION.state
    await h.message(location=Location(latitude=46, longitude=66))
    await h.click("submit")
    data = h.api.create.call_args.args[0]
    assert data["application_type"] == "GAS_LEAK" and data["meter_photo_id"] != data["leak_photo_id"]


async def test_mpi_calendar_and_stale_callback(h):
    await h.start_type("MPI_REMOVAL")
    await h.click("date:" + today().isoformat(), message_id=1)
    assert await h.context.get_state() == Flow.MPI_WAITING_DATE.state
    await h.click("date:" + today().isoformat())
    assert await h.context.get_state() == Flow.MPI_CONFIRM.state
    await h.click("edit")
    await h.message("31.02.2026")
    assert await h.context.get_state() == Flow.MPI_WAITING_DATE.state
    await h.message(today().strftime("%d.%m.%Y"))
    await h.click("submit")
    data = h.api.create.call_args.args[0]
    assert data["requested_date"] == today().isoformat() and "latitude" not in data


async def test_failed_submit_keeps_idempotency_and_state(h):
    await h.start_type("MPI_REMOVAL")
    await h.message(today().strftime("%d.%m.%Y"))
    key = (await h.context.get_data())["idempotency_key"]
    h.api.create.side_effect = APIError("offline")
    with pytest.raises(APIError):
        await h.click("submit")
    assert await h.context.get_state() == Flow.MPI_CONFIRM.state
    assert (await h.context.get_data())["idempotency_key"] == key


def test_date_and_bounded_download():
    assert valid_date("yesterday") is None
    assert valid_date("01.01.2000") is None
    assert valid_date(today().strftime("%d.%m.%Y")) == today()
    buffer = BoundedBuffer(3)
    with pytest.raises(APIError):
        buffer.write(b"1234")


async def test_unknown_account_shows_not_found_and_offers_emergency(h):
    h.api.account.side_effect = None
    h.api.account.return_value = {"verified": False}
    await h.message("/start", entities=[{"type": "bot_command", "offset": 0, "length": 6}])
    await h.message("12345678")
    assert await h.context.get_state() == Flow.ACCOUNT_NOT_FOUND.state
    assert "табылмады" in h.session.messages[-1].text
    assert all("Test resident" not in message.text for message in h.session.messages)


async def test_known_account_shows_resident_immediately(h):
    verified = {"verified": True, "account": {"id": 2, "account_number": "00123456", "meter_number": "M-123",
                "full_name": "Verified Resident", "address": "Verified address"}}
    h.api.account.side_effect = None
    h.api.account.return_value = verified
    await h.message("/start", entities=[{"type": "bot_command", "offset": 0, "length": 6}])
    await h.message("00123456")
    h.api.account.assert_awaited_with(123456, "00123456")
    assert await h.context.get_state() == Flow.CONFIRM_ACCOUNT.state
    assert (await h.context.get_data())["personal_account"] == "00123456"
    assert "Verified Resident" in h.session.messages[-1].text
    assert "Verified address" in h.session.messages[-1].text


async def test_reading_flow_requires_photo_and_confirms(h):
    h.api.reading.return_value = {"id": "reading-1"}
    await h.message("/start", entities=[{"type": "bot_command", "offset": 0, "length": 6}])
    await h.message("12345678")
    await h.click("account:yes")
    await h.click("reading:start")
    await h.message("123.125")
    assert await h.context.get_state() == Flow.READING_PHOTO.state
    h.api.reading.assert_not_awaited()
    await h.message(photo=[PhotoSize(file_id="reading", file_unique_id="reading-photo", width=20, height=20)])
    assert await h.context.get_state() == Flow.READING_CONFIRM.state
    await h.click("reading:submit")
    assert h.api.reading.call_args.args[0]["photo_id"] == "11111111-1111-4111-8111-111111111111"
    assert h.api.reading.call_args.args[0]["telegram_user_id"] == 123456
    assert await h.context.get_state() is None


async def test_unfound_account_emergency_still_available(h):
    h.api.account.side_effect = None
    h.api.account.return_value = {"verified": False}
    await h.message("/start", entities=[{"type": "bot_command", "offset": 0, "length": 6}])
    await h.message("12345678")
    await h.message("⚠️ Авариялық өтінім")
    assert await h.context.get_state() == Flow.GAS_WAITING_METER_PHOTO.state
    assert (await h.context.get_data())["application_type"] == "GAS_LEAK"
