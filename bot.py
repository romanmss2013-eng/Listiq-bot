"""
Listiq Bot — главный файл запуска
"""
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import config
from services.database import init_db
from services.scheduler import run_scheduler
from handlers import start, analyze, payment, referral, admin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    if not config.BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан в переменных окружения")
    if not config.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY не задан")

    init_db()

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(start.router)
    dp.include_router(analyze.router)
    dp.include_router(payment.router)
    dp.include_router(referral.router)
    dp.include_router(admin.router)

    asyncio.create_task(run_scheduler(bot))

    logger.info("🚀 Listiq бот запущен")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
