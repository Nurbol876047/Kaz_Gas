import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand
from bot.config import Settings
from bot.handlers import router
from bot.middlewares import Guard
from bot.services import Backend


async def main():
    config = Settings()
    logging.basicConfig(level=logging.INFO)
    storage = RedisStorage.from_url(config.redis_url, state_ttl=86400, data_ttl=86400)
    dispatcher = Dispatcher(storage=storage, events_isolation=storage.create_isolation(lock_kwargs={"timeout": 120}))
    guard = Guard(storage.redis)
    router.message.outer_middleware(guard)
    router.callback_query.outer_middleware(guard)
    dispatcher.include_router(router)
    backend = Backend(config.backend_url, config.bot_api_key)
    async with Bot(config.bot_token) as bot:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Өтінім қалдыру"),
                BotCommand(command="applications", description="Менің өтінімдерім"),
                BotCommand(command="readings", description="Менің көрсеткіштерім"),
                BotCommand(command="contact", description="Байланыс"),
                BotCommand(command="menu", description="Басты мәзір"),
                BotCommand(command="cancel", description="Бас тарту"),
            ]
        )
        await bot.delete_webhook(drop_pending_updates=False)
        try:
            await dispatcher.start_polling(
                bot, backend=backend, timezone=config.timezone, allowed_updates=["message", "callback_query"]
            )
        finally:
            await backend.client.aclose()
            await storage.close()


if __name__ == "__main__":
    asyncio.run(main())
