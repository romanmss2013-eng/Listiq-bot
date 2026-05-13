"""
Платёжный сервис — ЮKassa
Создание платежей, проверка статуса, возврат средств
"""
import uuid
import logging
import aiohttp
from config import config

logger = logging.getLogger(__name__)

YUKASSA_BASE = "https://api.yookassa.ru/v3"

PLANS = {
    "month": {
        "label": "Старт — 30 дней",
        "price": config.PRICE_MONTH,
        "days": config.DAYS_MONTH,
        "description": "Listiq Старт — доступ на 30 дней",
    },
    "6months": {
        "label": "Рост — 180 дней",
        "price": config.PRICE_6MONTHS,
        "days": config.DAYS_6MONTHS,
        "description": "Listiq Рост — доступ на 180 дней",
    },
    "year": {
        "label": "Бизнес — 365 дней",
        "price": config.PRICE_YEAR,
        "days": config.DAYS_YEAR,
        "description": "Listiq Бизнес — доступ на 365 дней",
    },
}


def _auth() -> aiohttp.BasicAuth:
    return aiohttp.BasicAuth(config.YUKASSA_SHOP_ID, config.YUKASSA_SECRET_KEY)


async def create_payment(telegram_id: int, plan: str) -> dict:
    """
    Создаёт платёж в ЮKassa.
    Возвращает {"payment_id": ..., "confirmation_url": ...}
    """
    if plan not in PLANS:
        raise ValueError(f"Неизвестный тариф: {plan}")

    plan_data = PLANS[plan]
    idempotence_key = str(uuid.uuid4())

    payload = {
        "amount": {
            "value": f"{plan_data['price'] / 100:.2f}",
            "currency": "RUB"
        },
        "confirmation": {
            "type": "redirect",
            "return_url": f"https://t.me/listiqbot?start=paid_{telegram_id}"
        },
        "capture": True,
        "description": plan_data["description"],
        "metadata": {
            "telegram_id": str(telegram_id),
            "plan": plan,
        }
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{YUKASSA_BASE}/payments",
            json=payload,
            auth=_auth(),
            headers={"Idempotence-Key": idempotence_key},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            data = await resp.json()

    if "id" not in data:
        logger.error(f"ЮKassa ошибка создания платежа: {data}")
        raise RuntimeError("Ошибка создания платежа. Попробуйте позже.")

    return {
        "payment_id": data["id"],
        "confirmation_url": data["confirmation"]["confirmation_url"],
        "amount": plan_data["price"],
        "plan": plan,
        "days": plan_data["days"],
    }


async def check_payment_status(payment_id: str) -> str:
    """Возвращает статус платежа: pending | waiting_for_capture | succeeded | canceled"""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{YUKASSA_BASE}/payments/{payment_id}",
            auth=_auth(),
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            data = await resp.json()
    return data.get("status", "unknown")


async def create_refund(payment_id: str, amount_kopecks: int) -> bool:
    """
    Создаёт возврат через ЮKassa.
    Возвращает True если успешно.
    """
    idempotence_key = str(uuid.uuid4())
    payload = {
        "payment_id": payment_id,
        "amount": {
            "value": f"{amount_kopecks / 100:.2f}",
            "currency": "RUB"
        }
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{YUKASSA_BASE}/refunds",
            json=payload,
            auth=_auth(),
            headers={"Idempotence-Key": idempotence_key},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            data = await resp.json()

    status = data.get("status")
    if status in ("succeeded", "pending"):
        logger.info(f"Возврат создан: {payment_id} → {status}")
        return True

    logger.error(f"Ошибка возврата {payment_id}: {data}")
    return False
