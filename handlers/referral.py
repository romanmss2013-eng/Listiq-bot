"""
Реферальная система
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from services.database import get_user, get_active_subscription
import logging

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data == "referral")
async def cb_referral(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if not user:
        await call.answer()
        return

    ref_code = user.get("referral_code", "")
    ref_link = f"https://t.me/listiqbot?start=ref_{ref_code}"

    text = (
        "👥 *Реферальная программа*\n\n"
        "Пригласи друга — получи *+7 дней* к подписке.\n\n"
        "Как это работает:\n"
        "1. Поделись своей ссылкой\n"
        "2. Друг переходит и оплачивает любой тариф\n"
        "3. Тебе автоматически добавляется 7 дней\n\n"
        f"Твоя ссылка:\n`{ref_link}`\n\n"
        "_Количество приглашений не ограничено_"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться ссылкой", switch_inline_query=f"Попробуй Listiq — SEO для маркетплейсов. Моя ссылка: {ref_link}")],
        [InlineKeyboardButton(text="← Назад", callback_data="back_menu")],
    ])

    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    await call.answer()
