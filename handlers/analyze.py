"""
Хендлер анализа — главная функция Listiq
Четыре режима: карточка, ниша, диагностика продаж, отзывы
"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from services.analyzer import (
    generate_seo_package, generate_niche_analysis,
    generate_why_no_sales, generate_review_response
)
from services.database import (
    get_active_subscription, use_free_request,
    count_today_requests, save_request, get_user_history
)
from config import config

logger = logging.getLogger(__name__)
router = Router()


class States(StatesGroup):
    # Анализ карточки
    card_marketplace = State()
    card_name = State()
    card_category = State()
    card_price = State()
    card_description = State()
    card_competitors = State()
    card_problem = State()
    # Ниша
    niche_input = State()
    # Нет продаж
    nosales_input = State()
    # Отзыв
    review_product = State()
    review_text = State()


def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="← Главное меню", callback_data="back_menu")]
    ])


def after_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Новая карточка", callback_data="analyze_card")],
        [InlineKeyboardButton(text="🔍 Анализ ниши", callback_data="analyze_niche")],
        [InlineKeyboardButton(text="← Меню", callback_data="back_menu")],
    ])


async def check_access(telegram_id: int):
    sub = get_active_subscription(telegram_id)
    if sub:
        today = count_today_requests(telegram_id)
        if today >= config.DAILY_REQUEST_LIMIT:
            return False, "daily_limit"
        return True, "subscribed"
    if use_free_request(telegram_id):
        return True, "free"
    return False, "no_access"


def no_access_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Выбрать тариф", callback_data="show_plans")],
        [InlineKeyboardButton(text="← Меню", callback_data="back_menu")],
    ])


# ── РЕЖИМ 1: АНАЛИЗ КАРТОЧКИ ───────────────────────────────────────────────

@router.callback_query(F.data == "analyze_card")
async def cb_card_start(call: CallbackQuery, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Wildberries", callback_data="mp_wb")],
        [InlineKeyboardButton(text="Ozon", callback_data="mp_ozon")],
        [InlineKeyboardButton(text="Яндекс Маркет", callback_data="mp_ym")],
        [InlineKeyboardButton(text="← Назад", callback_data="back_menu")],
    ])
    await call.message.edit_text(
        "📦 *Анализ карточки товара*\n\nВыбери маркетплейс:",
        parse_mode="Markdown", reply_markup=kb
    )
    await state.set_state(States.card_marketplace)
    await call.answer()


@router.callback_query(F.data.startswith("mp_"))
async def cb_marketplace(call: CallbackQuery, state: FSMContext):
    mp_map = {"mp_wb": "Wildberries", "mp_ozon": "Ozon", "mp_ym": "Яндекс Маркет"}
    marketplace = mp_map.get(call.data, "Wildberries")
    await state.update_data(marketplace=marketplace)
    await call.message.edit_text(
        f"🏪 *{marketplace}*\n\nНапиши название товара:",
        parse_mode="Markdown", reply_markup=back_kb()
    )
    await state.set_state(States.card_name)
    await call.answer()


@router.message(States.card_name)
async def step_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("Категория товара (например: Спорт / Термосы):", reply_markup=back_kb())
    await state.set_state(States.card_category)


@router.message(States.card_category)
async def step_category(message: Message, state: FSMContext):
    await state.update_data(category=message.text.strip())
    await message.answer("Цена в рублях (только цифра, например: 1290):", reply_markup=back_kb())
    await state.set_state(States.card_price)


@router.message(States.card_price)
async def step_price(message: Message, state: FSMContext):
    await state.update_data(price=message.text.strip())
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить →", callback_data="skip_description")],
        [InlineKeyboardButton(text="← Назад", callback_data="back_menu")],
    ])
    await message.answer(
        "Текущее описание карточки (скопируй из личного кабинета).\n"
        "Если нет — нажми Пропустить:", reply_markup=kb
    )
    await state.set_state(States.card_description)


@router.callback_query(F.data == "skip_description")
async def skip_desc(call: CallbackQuery, state: FSMContext):
    await state.update_data(description="")
    await call.message.edit_text(
        "Главные конкуренты — названия товаров или брендов (через запятую).\n"
        "Если не знаешь — напиши «не знаю»:",
        reply_markup=back_kb()
    )
    await state.set_state(States.card_competitors)
    await call.answer()


@router.message(States.card_description)
async def step_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await message.answer(
        "Главные конкуренты (названия через запятую).\nЕсли не знаешь — напиши «не знаю»:",
        reply_markup=back_kb()
    )
    await state.set_state(States.card_competitors)


@router.message(States.card_competitors)
async def step_competitors(message: Message, state: FSMContext):
    await state.update_data(competitors=message.text.strip())
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить →", callback_data="skip_problem")],
        [InlineKeyboardButton(text="← Назад", callback_data="back_menu")],
    ])
    await message.answer(
        "Опиши проблему — что конкретно не устраивает? "
        "(мало показов, нет заказов, плохой CTR)\n"
        "Или нажми Пропустить:",
        reply_markup=kb
    )
    await state.set_state(States.card_problem)


@router.callback_query(F.data == "skip_problem")
async def skip_problem(call: CallbackQuery, state: FSMContext):
    await state.update_data(problem="")
    await call.answer()
    await _run_card_analysis(call.message, state, call.from_user.id)


@router.message(States.card_problem)
async def step_problem(message: Message, state: FSMContext):
    await state.update_data(problem=message.text.strip())
    await _run_card_analysis(message, state, message.from_user.id)


async def _run_card_analysis(message, state: FSMContext, telegram_id: int):
    allowed, reason = await check_access(telegram_id)
    if not allowed:
        await state.clear()
        text = (
            f"⏳ Дневной лимит исчерпан. Обновится в 00:00 по МСК."
            if reason == "daily_limit" else
            "🔒 Бесплатный запрос использован. Выбери тариф чтобы продолжить."
        )
        await message.answer(text, reply_markup=no_access_kb())
        return

    data = await state.get_data()
    await state.clear()

    wait = await message.answer(
        "⏳ Анализирую карточку...\n_Обычно 20–40 секунд_",
        parse_mode="Markdown"
    )

    try:
        result = await generate_seo_package(data)
        save_request(telegram_id, data.get("name", ""), data.get("marketplace", ""), result)
        await wait.delete()

        if len(result) > 4000:
            parts = _split(result, 4000)
            for i, part in enumerate(parts):
                kb = after_kb() if i == len(parts) - 1 else None
                await message.answer(part, parse_mode="Markdown", reply_markup=kb)
        else:
            await message.answer(result, parse_mode="Markdown", reply_markup=after_kb())

        if reason == "free":
            await message.answer(
                "💡 Это был твой бесплатный запрос.\n"
                "Подключи тариф — анализируй любое количество товаров.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Выбрать тариф", callback_data="show_plans")]
                ])
            )
    except Exception as e:
        logger.error(f"Ошибка анализа: {e}", exc_info=True)
        await wait.delete()
        await message.answer("⚠️ Ошибка при анализе. Попробуй ещё раз.")


# ── РЕЖИМ 2: АНАЛИЗ НИШИ ──────────────────────────────────────────────────

@router.callback_query(F.data == "analyze_niche")
async def cb_niche(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "🔍 *Анализ ниши*\n\n"
        "Напиши название товара или категории которую хочешь продавать.\n\n"
        "_Например: термосы, детские игрушки, чехлы для телефона_",
        parse_mode="Markdown", reply_markup=back_kb()
    )
    await state.set_state(States.niche_input)
    await call.answer()


@router.message(States.niche_input)
async def handle_niche(message: Message, state: FSMContext):
    allowed, reason = await check_access(message.from_user.id)
    if not allowed:
        await state.clear()
        await message.answer(
            "🔒 Выбери тариф чтобы использовать анализ ниш.",
            reply_markup=no_access_kb()
        )
        return

    niche = message.text.strip()
    await state.clear()
    wait = await message.answer("⏳ Анализирую нишу...")

    try:
        result = await generate_niche_analysis(niche)
        save_request(message.from_user.id, niche, "Анализ ниши", result)
        await wait.delete()
        await message.answer(result, parse_mode="Markdown", reply_markup=after_kb())

        if reason == "free":
            await message.answer(
                "💡 Бесплатный запрос использован. Подключи тариф для продолжения.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Тарифы", callback_data="show_plans")]
                ])
            )
    except Exception as e:
        logger.error(f"Ошибка анализа ниши: {e}")
        await wait.delete()
        await message.answer("⚠️ Ошибка. Попробуй ещё раз.")


# ── РЕЖИМ 3: ПОЧЕМУ НЕТ ПРОДАЖ ────────────────────────────────────────────

@router.callback_query(F.data == "analyze_nosales")
async def cb_nosales(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "📉 *Почему нет продаж?*\n\n"
        "Опиши свою ситуацию подробно:\n"
        "— что продаёшь и на каком маркетплейсе\n"
        "— сколько времени в продаже\n"
        "— какие показатели (просмотры, заказы)\n"
        "— что уже пробовал\n\n"
        "_Чем подробнее — тем точнее диагноз_",
        parse_mode="Markdown", reply_markup=back_kb()
    )
    await state.set_state(States.nosales_input)
    await call.answer()


@router.message(States.nosales_input)
async def handle_nosales(message: Message, state: FSMContext):
    allowed, reason = await check_access(message.from_user.id)
    if not allowed:
        await state.clear()
        await message.answer("🔒 Выбери тариф.", reply_markup=no_access_kb())
        return

    situation = message.text.strip()
    await state.clear()
    wait = await message.answer("⏳ Ставлю диагноз...")

    try:
        result = await generate_why_no_sales(situation)
        save_request(message.from_user.id, "Диагностика продаж", "Анализ", result)
        await wait.delete()
        await message.answer(result, parse_mode="Markdown", reply_markup=after_kb())
    except Exception as e:
        logger.error(f"Ошибка диагностики: {e}")
        await wait.delete()
        await message.answer("⚠️ Ошибка. Попробуй ещё раз.")


# ── РЕЖИМ 4: ОТВЕТЫ НА ОТЗЫВЫ ─────────────────────────────────────────────

@router.callback_query(F.data == "review_start")
async def cb_review(call: CallbackQuery, state: FSMContext):
    sub = get_active_subscription(call.from_user.id)
    if not sub:
        await call.answer("Доступно с тарифа Рост и выше", show_alert=True)
        return
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить →", callback_data="skip_review_product")],
        [InlineKeyboardButton(text="← Назад", callback_data="back_menu")],
    ])
    await call.message.edit_text(
        "💬 *Ответ на отзыв*\n\nНазвание товара (необязательно):",
        parse_mode="Markdown", reply_markup=kb
    )
    await state.set_state(States.review_product)
    await call.answer()


@router.callback_query(F.data == "skip_review_product")
async def skip_review_product(call: CallbackQuery, state: FSMContext):
    await state.update_data(review_product="")
    await call.message.edit_text(
        "Вставь текст отзыва покупателя:",
        reply_markup=back_kb()
    )
    await state.set_state(States.review_text)
    await call.answer()


@router.message(States.review_product)
async def step_review_product(message: Message, state: FSMContext):
    await state.update_data(review_product=message.text.strip())
    await message.answer("Вставь текст отзыва покупателя:", reply_markup=back_kb())
    await state.set_state(States.review_text)


@router.message(States.review_text)
async def handle_review(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    wait = await message.answer("⏳ Составляю ответ...")
    try:
        result = await generate_review_response(
            message.text.strip(),
            data.get("review_product", "")
        )
        await wait.delete()
        await message.answer(
            f"💬 *Готовый ответ:*\n\n{result}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💬 Ещё отзыв", callback_data="review_start")],
                [InlineKeyboardButton(text="← Меню", callback_data="back_menu")],
            ])
        )
    except Exception as e:
        logger.error(f"Ошибка ответа на отзыв: {e}")
        await wait.delete()
        await message.answer("⚠️ Ошибка. Попробуй ещё раз.")


# ── ИСТОРИЯ ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "my_history")
async def cb_history(call: CallbackQuery):
    history = get_user_history(call.from_user.id, limit=5)
    if not history:
        await call.message.edit_text(
            "📋 История пуста. Начни с анализа первого товара.",
            reply_markup=back_kb()
        )
        await call.answer()
        return

    lines = ["📋 *Последние запросы:*\n"]
    for i, item in enumerate(history, 1):
        from datetime import datetime
        dt = datetime.fromisoformat(item["created_at"])
        lines.append(f"{i}. {item['marketplace']} — {dt.strftime('%d.%m %H:%M')}")
        url = item['url']
        lines.append(f"   _{url[:40]}{'...' if len(url) > 40 else ''}_")

    await call.message.edit_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=back_kb()
    )
    await call.answer()


# ── FAQ ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "faq")
async def cb_faq(call: CallbackQuery):
    await call.message.edit_text(
        "❓ *Частые вопросы*\n\n"
        "*Через сколько будет результат?*\n"
        "Маркетплейс переиндексирует карточку за 24–72 ч. "
        "Рост позиций виден через 3–7 дней.\n\n"
        "*Что значит безлимит?*\n"
        f"До {config.DAILY_REQUEST_LIMIT} запросов в сутки — "
        "достаточно для любого объёма карточек.\n\n"
        "*Работает для новых товаров?*\n"
        "Да. Анализ строится на логике ниши, не на истории продаж.\n\n"
        "*Как вернуть деньги?*\n"
        "Напиши /refund — бот проверит условия и вернёт автоматически.\n\n"
        "*Нужна регистрация?*\n"
        "Нет. Достаточно Telegram.",
        parse_mode="Markdown", reply_markup=back_kb()
    )
    await call.answer()


# ── BACK ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "back_menu")
async def cb_back(call: CallbackQuery, state: FSMContext):
    await state.clear()
    sub = get_active_subscription(call.from_user.id)
    from handlers.start import main_menu_kb
    await call.message.edit_text(
        "Главное меню Listiq:", reply_markup=main_menu_kb(bool(sub))
    )
    await call.answer()


def _split(text: str, max_len: int) -> list:
    parts, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_len:
            parts.append(current)
            current = line + "\n"
        else:
            current += line + "\n"
    if current:
        parts.append(current)
    return parts
