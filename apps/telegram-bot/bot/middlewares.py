import logging
from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message
from bot.services import APIError


class Guard(BaseMiddleware):
    def __init__(self, redis):
        self.redis = redis

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        chat = data.get("event_chat")
        if user is None or user.is_bot or chat is None or chat.type != "private":
            return
        count = await self.redis.eval(
            "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],2) end; return n",
            1,
            f"bot-rate:{user.id}",
        )
        if count > 5:
            return
        try:
            return await handler(event, data)
        except (APIError, TelegramAPIError) as exc:
            logging.getLogger("bot").warning("Bot request failed; FSM preserved")
            message = event.message if isinstance(event, CallbackQuery) else event
            if isinstance(message, Message):
                await message.answer(
                    "⚠️ " + str(exc) if isinstance(exc, APIError) else
                    "⚠️ Сұраныс орындалмады. Деректеріңіз сақталды. Қайта көріңіз немесе /start басыңыз."
                )
