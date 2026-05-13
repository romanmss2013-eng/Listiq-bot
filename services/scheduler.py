"""
Планировщик фоновых задач:
- Уведомления об истечении подписки за 3 дня
- Уведомления рефереру о бонусе
"""
import asyncio
import logging
from datetime import datetime
from aiogram import Bot
from services.database import get_expiring_subscriptions, mark_expiry_notified
from config import config

logger = logging.getLogger(__name__)


async def notify_expiring(bot: Bot):
    """Уведомляем пользователей у которых подписка заканчивается через 3 дня"""
    expiring = get_expiring_subscriptions(in_days=config.NOTIFY_BEFORE_DAYS)

    for user in expiring:
        try:
            expires = datetime.fromisoformat(user["expires_at"])
            days_left = (expires - datetime.utcnow()).days

            await bot.send_message(
                user["telegram_id"],
                f"⏳ *Подписка заканчивается через {days_left} дн.*\n\n"
                f"Тариф: {user['plan']}\n"
                f"Истекает: {expires.strftime('%d.%m.%Y')}\n\n"
                "Продли сейчас чтобы не потерять доступ — "
                "при продлении дни суммируются.",
                parse_mode="Markdown",
            )
            mark_expiry_notified(user["telegram_id"])
            logger.info(f"Уведомление отправлено: {user['telegram_id']}")

        except Exception as e:
            logger.warning(f"Не удалось уведомить {user['telegram_id']}: {e}")


async def run_scheduler(bot: Bot):
    """Запускает задачи по расписанию каждые 6 часов"""
    logger.info("Планировщик запущен")
    while True:
        try:
            await notify_expiring(bot)
        except Exception as e:
            logger.error(f"Ошибка планировщика: {e}")
        await asyncio.sleep(6 * 3600)  # каждые 6 часов
