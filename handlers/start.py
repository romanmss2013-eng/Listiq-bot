from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from services.database import get_or_create_user, register_referral, get_active_subscription

router = Router()


def main_menu_kb(has_sub: bool = False) -> InlineKeyboardMarkup:
    buttons = []
    if not has_sub:
        buttons.append([InlineKeyboardButton(text="💳 Тарифы", callback_data="show_plans")])
    buttons += [
        [InlineKeyboardButton(text="📦 Анализ карточки товара", callback_data="analyze_card")],
        [InlineKeyboardButton(text="🔍 Стоит ли заходить в нишу?", callback_data="analyze_niche")],
        [InlineKeyboardButton(text="📉 Почему нет продаж?", callback_data="analyze_nosales")],
        [InlineKeyboardButton(text="💬 Ответить на отзыв", callback_data="review_start")],
        [InlineKeyboardButton(text="📋 История запросов", callback_data="my_history")],
        [InlineKeyboardButton(text="👥 Пригласить друга (+7 дней)", callback_data="referral")],
        [InlineKeyboardButton(text="❓ FAQ", callback_data="faq")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(CommandStart())
async def cmd_start(message: Message):
    args = message.text.split()
    ref_code = None
    if len(args) > 1 and args[1].startswith("ref_"):
        ref_code = args[1][4:]

    user = get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
    )

    if ref_code:
        register_referral(message.from_user.id, ref_code)

    sub = get_active_subscription(message.from_user.id)
    free_left = user.get("free_requests", 0)

    if sub:
        from datetime import datetime
        expires = datetime.fromisoformat(sub["expires_at"])
        days_left = (expires - datetime.utcnow()).days
        status = f"✅ Тариф *{_plan(sub['plan'])}* — осталось *{days_left} дн.*"
    elif free_left > 0:
        status = f"🎁 У тебя *1 бесплатный запрос* — попробуй прямо сейчас"
    else:
        status = "⚡ Бесплатный запрос использован — выбери тариф"

    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        f"*Listiq* — твой эксперт по продажам на маркетплейсах.\n\n"
        f"Что умею:\n"
        f"• Анализирую карточку и пишу SEO-описание\n"
        f"• Оцениваю нишу перед входом\n"
        f"• Нахожу причины почему нет продаж\n"
        f"• Пишу ответы на отзывы\n\n"
        f"{status}",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(bool(sub))
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    sub = get_active_subscription(message.from_user.id)
    await message.answer("Главное меню:", reply_markup=main_menu_kb(bool(sub)))


@router.message(Command("status"))
async def cmd_status(message: Message):
    user = get_or_create_user(message.from_user.id)
    sub = get_active_subscription(message.from_user.id)
    if sub:
        from datetime import datetime
        expires = datetime.fromisoformat(sub["expires_at"])
        days_left = (expires - datetime.utcnow()).days
        text = (f"📊 *Статус*\n\nТариф: *{_plan(sub['plan'])}*\n"
                f"Осталось: *{days_left} дн.*\nИстекает: {expires.strftime('%d.%m.%Y')}")
    else:
        text = f"📊 *Статус*\n\nПодписки нет\nБесплатных запросов: *{user.get('free_requests', 0)}*"
    await message.answer(text, parse_mode="Markdown")


def _plan(plan):
    return {"month": "Старт", "6months": "Рост", "year": "Бизнес"}.get(plan, plan)
