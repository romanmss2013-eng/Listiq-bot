"""
Админ-панель — статистика, рассылка
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from services.database import get_stats
from config import config
import logging

router = Router()
logger = logging.getLogger(__name__)


def is_admin(telegram_id: int) -> bool:
    return telegram_id in (config.ADMIN_IDS or [])


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        return

    stats = get_stats()
    revenue_rub = stats["revenue_kopecks"] // 100

    text = (
        "📊 *Listiq — Статистика*\n\n"
        f"👥 Всего пользователей: *{stats['total_users']}*\n"
        f"✅ Активных подписок: *{stats['active_subs']}*\n"
        f"📦 Всего запросов: *{stats['total_requests']}*\n"
        f"💰 Выручка: *{revenue_rub:,}₽*"
    )

    await message.answer(text, parse_mode="Markdown")


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    """Рассылка всем пользователям. Формат: /broadcast текст"""
    if not is_admin(message.from_user.id):
        return

    text = message.text.replace("/broadcast", "").strip()
    if not text:
        await message.answer("Формат: /broadcast <текст>")
        return

    from services.database import get_conn
    with get_conn() as conn:
        users = conn.execute("SELECT telegram_id FROM users").fetchall()

    from aiogram import Bot
    bot = message.bot
    sent, failed = 0, 0

    for user in users:
        try:
            await bot.send_message(user["telegram_id"], text, parse_mode="Markdown")
            sent += 1
        except Exception:
            failed += 1

    await message.answer(f"✅ Отправлено: {sent}\n❌ Ошибок: {failed}")
