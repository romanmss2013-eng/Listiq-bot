"""
Хендлер оплаты — тарифы, создание платежей, возврат
"""
import logging
import asyncio
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from services.payment_service import create_payment, check_payment_status, create_refund, PLANS
from services.database import (
    create_payment as db_create_payment,
    confirm_payment, get_payment_by_id,
    mark_payment_refunded, create_subscription,
    get_active_subscription, get_user, count_today_requests,
    give_referral_bonus, add_bonus_days
)
from config import config

logger = logging.getLogger(__name__)
router = Router()


def plans_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Старт — 1 490₽ / 30 дней", callback_data="pay_month")],
        [InlineKeyboardButton(text="🚀 Рост — 7 990₽ / 180 дней ⭐", callback_data="pay_6months")],
        [InlineKeyboardButton(text="💼 Бизнес — 12 990₽ / 365 дней", callback_data="pay_year")],
        [InlineKeyboardButton(text="← Назад", callback_data="back_menu")],
    ])


@router.callback_query(F.data == "show_plans")
async def cb_show_plans(call: CallbackQuery):
    sub = get_active_subscription(call.from_user.id)
    sub_note = ""
    if sub:
        from datetime import datetime
        days_left = (datetime.fromisoformat(sub["expires_at"]) - datetime.utcnow()).days
        sub_note = f"\n\n✅ У тебя активен тариф. Осталось *{days_left} дн.* При оплате — дни прибавятся."

    text = (
        "💳 *Тарифы Listiq*\n\n"
        "Все тарифы включают:\n"
        "• Безлимитный анализ карточек\n"
        "• WB + Ozon + Яндекс Маркет\n"
        "• SEO-описание + 5 заголовков\n"
        "• 30+ ключевых слов\n"
        "• Анализ конкурентов\n"
        "• История запросов\n"
        "• База знаний и FAQ\n\n"
        "Тариф *Рост* и выше — дополнительно:\n"
        "• Ответы на отзывы покупателей\n"
        "• Автообновление базы ключей\n"
        "• Ранний доступ к новым функциям"
        + sub_note
    )
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=plans_kb())
    await call.answer()


@router.callback_query(F.data.startswith("pay_"))
async def cb_pay(call: CallbackQuery):
    plan = call.data.replace("pay_", "")
    if plan not in PLANS:
        await call.answer("Неизвестный тариф", show_alert=True)
        return

    await call.answer("Создаём платёж...")

    try:
        payment = await create_payment(call.from_user.id, plan)

        # Сохраняем платёж в БД
        db_create_payment(
            telegram_id=call.from_user.id,
            payment_id=payment["payment_id"],
            plan=plan,
            amount=payment["amount"],
        )

        plan_data = PLANS[plan]
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=payment["confirmation_url"])],
            [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"check_{payment['payment_id']}")],
            [InlineKeyboardButton(text="← Назад", callback_data="show_plans")],
        ])

        await call.message.edit_text(
            f"💳 *{plan_data['label']}*\n\n"
            f"Сумма: *{plan_data['price'] // 100}₽*\n"
            f"Доступ: *{plan_data['days']} дней*\n\n"
            "Нажми кнопку ниже для оплаты.\n"
            "После оплаты нажми «Я оплатил» — доступ откроется автоматически.",
            parse_mode="Markdown",
            reply_markup=kb
        )

    except Exception as e:
        logger.error(f"Ошибка создания платежа: {e}")
        await call.message.answer(
            "⚠️ Не удалось создать платёж. Попробуй через несколько минут."
        )


@router.callback_query(F.data.startswith("check_"))
async def cb_check_payment(call: CallbackQuery):
    payment_id = call.data.replace("check_", "")

    await call.answer("Проверяем платёж...")

    try:
        status = await check_payment_status(payment_id)

        if status == "succeeded":
            payment = confirm_payment(payment_id)
            if not payment:
                await call.message.answer("ℹ️ Платёж уже был активирован ранее.")
                return

            plan_data = PLANS[payment["plan"]]
            create_subscription(
                telegram_id=payment["telegram_id"],
                plan=payment["plan"],
                days=plan_data["days"],
            )

            # Начисляем бонус рефереру
            referrer_tg = give_referral_bonus(payment["telegram_id"])
            if referrer_tg:
                add_bonus_days(referrer_tg, config.REFERRAL_BONUS_DAYS)
                # Уведомление рефереру отправляется из scheduler

            from handlers.start import main_menu_kb
            await call.message.edit_text(
                f"🎉 *Оплата подтверждена!*\n\n"
                f"Тариф *{plan_data['label']}* активирован.\n"
                f"Доступ открыт на *{plan_data['days']} дней*.\n\n"
                "Отправь ссылку на товар — начнём анализировать.",
                parse_mode="Markdown",
                reply_markup=main_menu_kb(has_sub=True)
            )

        elif status in ("pending", "waiting_for_capture"):
            await call.message.answer(
                "⏳ Платёж ещё обрабатывается.\n"
                "Обычно это занимает 1–2 минуты. Нажми «Я оплатил» ещё раз."
            )
        elif status == "canceled":
            await call.message.answer(
                "❌ Платёж отменён.\n\nПопробуй создать новый через меню тарифов.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Тарифы", callback_data="show_plans")]
                ])
            )
        else:
            await call.message.answer(f"ℹ️ Статус платежа: {status}. Попробуй позже.")

    except Exception as e:
        logger.error(f"Ошибка проверки платежа {payment_id}: {e}")
        await call.message.answer("⚠️ Не удалось проверить статус. Попробуй позже.")


# ── ВОЗВРАТ ────────────────────────────────────────────────────────────────

@router.message(Command("refund"))
async def cmd_refund(message: Message):
    """Автоматический возврат если пользователь не использовал запросы"""
    from services.database import get_user
    import sqlite3
    from services.database import get_conn

    telegram_id = message.from_user.id

    # Ищем последний оплаченный платёж
    with get_conn() as conn:
        payment = conn.execute(
            """SELECT p.* FROM payments p
               JOIN users u ON u.id = p.user_id
               WHERE u.telegram_id = ? AND p.status = 'paid'
               ORDER BY p.created_at DESC LIMIT 1""",
            (telegram_id,)
        ).fetchone()

    if not payment:
        await message.answer(
            "ℹ️ Оплаченных подписок не найдено.\n\n"
            "Если ты считаешь что произошла ошибка — напиши в поддержку @listiq_support"
        )
        return

    payment = dict(payment)

    # Проверяем: были ли запросы после оплаты
    with get_conn() as conn:
        requests_after = conn.execute(
            """SELECT COUNT(*) as cnt FROM requests r
               JOIN users u ON u.id = r.user_id
               WHERE u.telegram_id = ? AND r.created_at >= ?""",
            (telegram_id, payment["created_at"])
        ).fetchone()

    if requests_after and requests_after["cnt"] > 0:
        await message.answer(
            "❌ *Возврат невозможен*\n\n"
            "Ты уже использовал сервис после оплаты.\n\n"
            "Согласно публичной оферте, цифровые услуги возврату "
            "не подлежат после начала использования.\n\n"
            "Если есть вопросы — @listiq_support",
            parse_mode="Markdown"
        )
        return

    # Проверяем срок (3 дня)
    from datetime import datetime, timedelta
    paid_at = datetime.fromisoformat(payment["created_at"])
    if datetime.utcnow() - paid_at > timedelta(days=3):
        await message.answer(
            "❌ Срок возврата истёк.\n\n"
            "Возврат возможен в течение 3 дней с момента оплаты "
            "при условии неиспользования сервиса.\n\n"
            "По вопросам — @listiq_support"
        )
        return

    # Всё окей — делаем возврат
    await message.answer("⏳ Инициируем возврат...")

    try:
        success = await create_refund(payment["payment_id"], payment["amount"])

        if success:
            mark_payment_refunded(payment["payment_id"])
            # Деактивируем подписку
            with get_conn() as conn:
                conn.execute(
                    """UPDATE subscriptions SET active = 0
                       WHERE user_id = (SELECT id FROM users WHERE telegram_id = ?)""",
                    (telegram_id,)
                )

            await message.answer(
                "✅ *Возврат инициирован*\n\n"
                f"Сумма: *{payment['amount'] // 100}₽*\n"
                "Деньги вернутся на карту в течение *1–3 рабочих дней*.\n\n"
                "Статус можно отследить в банковском приложении.",
                parse_mode="Markdown"
            )
        else:
            await message.answer(
                "⚠️ Не удалось автоматически инициировать возврат.\n"
                "Напиши в поддержку — @listiq_support, разберёмся вручную."
            )

    except Exception as e:
        logger.error(f"Ошибка возврата для {telegram_id}: {e}")
        await message.answer(
            "⚠️ Техническая ошибка при возврате.\n"
            "Напиши @listiq_support — вернём деньги вручную."
        )
