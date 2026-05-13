"""
Парсер маркетплейсов — WB, Ozon, Яндекс Маркет
Получает данные товара и конкурентов по ссылке
"""
import re
import logging
import asyncio
import aiohttp
from dataclasses import dataclass

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "ru-RU,ru;q=0.9",
}


@dataclass
class ProductData:
    marketplace: str
    name: str
    description: str
    category: str
    brand: str
    price: int
    rating: float
    reviews_count: int
    article: str
    current_keywords: list[str]
    competitors: list[dict]   # [{name, rating, reviews, keywords}]
    raw_url: str


def detect_marketplace(url: str) -> str | None:
    url = url.lower()
    if "wildberries.ru" in url or "wb.ru" in url:
        return "wildberries"
    if "ozon.ru" in url:
        return "ozon"
    if "market.yandex" in url:
        return "yandex_market"
    return None


def extract_wb_article(url: str) -> str | None:
    m = re.search(r"/catalog/(\d+)/", url)
    return m.group(1) if m else None


def extract_ozon_id(url: str) -> str | None:
    m = re.search(r"/product/[^/]+-(\d+)/?", url)
    return m.group(1) if m else None


async def fetch_wb_product(article: str, session: aiohttp.ClientSession) -> dict:
    """Получаем данные товара WB через официальное API карточек"""
    api_url = f"https://card.wb.ru/cards/v1/detail?appType=1&curr=rub&dest=-1257786&spp=30&nm={article}"
    async with session.get(api_url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as r:
        data = await r.json(content_type=None)

    products = data.get("data", {}).get("products", [])
    if not products:
        raise ValueError(f"Товар WB {article} не найден")

    p = products[0]
    return {
        "name": p.get("name", ""),
        "brand": p.get("brand", ""),
        "category": p.get("subjectName", ""),
        "price": p.get("salePriceU", 0) // 100,
        "rating": p.get("reviewRating", 0),
        "reviews_count": p.get("feedbacks", 0),
        "article": article,
        "description": p.get("description", ""),
    }


async def fetch_wb_competitors(category_name: str, session: aiohttp.ClientSession) -> list[dict]:
    """Получаем топ товаров по категории для анализа конкурентов"""
    search_url = (
        f"https://search.wb.ru/exactmatch/ru/common/v4/search"
        f"?appType=1&curr=rub&dest=-1257786&query={category_name}&sort=popular&spp=30&page=1"
    )
    try:
        async with session.get(search_url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as r:
            data = await r.json(content_type=None)
        products = data.get("data", {}).get("products", [])[:8]
        return [
            {
                "name": p.get("name", ""),
                "brand": p.get("brand", ""),
                "rating": p.get("reviewRating", 0),
                "reviews": p.get("feedbacks", 0),
                "price": p.get("salePriceU", 0) // 100,
            }
            for p in products
        ]
    except Exception as e:
        logger.warning(f"Не удалось получить конкурентов WB: {e}")
        return []


async def fetch_ozon_product(product_id: str, session: aiohttp.ClientSession) -> dict:
    """Получаем данные товара Ozon"""
    api_url = f"https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url=/product/{product_id}/"
    try:
        async with session.get(api_url, headers={**HEADERS, "x-o3-app-name": "ozonapp_android"}, timeout=aiohttp.ClientTimeout(total=15)) as r:
            data = await r.json(content_type=None)

        # Ищем данные в структуре ответа
        widget_states = data.get("widgetStates", {})
        product_info = {}

        for key, val in widget_states.items():
            if "webProductHeading" in key:
                import json
                try:
                    info = json.loads(val) if isinstance(val, str) else val
                    product_info = info
                    break
                except Exception:
                    pass

        name = product_info.get("title", f"Товар Ozon #{product_id}")
        return {
            "name": name,
            "brand": product_info.get("brand", {}).get("name", ""),
            "category": product_info.get("breadcrumbs", [{}])[-1].get("title", ""),
            "price": 0,
            "rating": product_info.get("rating", 0),
            "reviews_count": product_info.get("reviewsCount", 0),
            "article": product_id,
            "description": "",
        }
    except Exception as e:
        logger.warning(f"Ошибка парсинга Ozon: {e}")
        return {
            "name": f"Товар Ozon #{product_id}",
            "brand": "", "category": "", "price": 0,
            "rating": 0, "reviews_count": 0,
            "article": product_id, "description": "",
        }


async def get_product_data(url: str) -> ProductData:
    """
    Главная функция — получает данные товара по ссылке.
    Возвращает ProductData со всем необходимым для анализа.
    """
    marketplace = detect_marketplace(url)
    if not marketplace:
        raise ValueError("Ссылка не распознана. Поддерживаются WB, Ozon, Яндекс Маркет.")

    async with aiohttp.ClientSession() as session:

        if marketplace == "wildberries":
            article = extract_wb_article(url)
            if not article:
                # Пробуем найти артикул в конце URL
                m = re.search(r"(\d{6,})", url)
                article = m.group(1) if m else None
            if not article:
                raise ValueError("Не удалось получить артикул из ссылки WB.")

            product = await fetch_wb_product(article, session)
            competitors = await fetch_wb_competitors(product["category"], session)

            return ProductData(
                marketplace="Wildberries",
                name=product["name"],
                description=product["description"],
                category=product["category"],
                brand=product["brand"],
                price=product["price"],
                rating=product["rating"],
                reviews_count=product["reviews_count"],
                article=article,
                current_keywords=_extract_keywords(product["name"] + " " + product["description"]),
                competitors=competitors,
                raw_url=url,
            )

        elif marketplace == "ozon":
            product_id = extract_ozon_id(url)
            if not product_id:
                m = re.search(r"(\d{6,})", url)
                product_id = m.group(1) if m else "unknown"

            product = await fetch_ozon_product(product_id, session)
            return ProductData(
                marketplace="Ozon",
                name=product["name"],
                description=product["description"],
                category=product["category"],
                brand=product["brand"],
                price=product["price"],
                rating=product["rating"],
                reviews_count=product["reviews_count"],
                article=product_id,
                current_keywords=_extract_keywords(product["name"]),
                competitors=[],
                raw_url=url,
            )

        elif marketplace == "yandex_market":
            # Яндекс Маркет — базовая версия
            return ProductData(
                marketplace="Яндекс Маркет",
                name="Товар с Яндекс Маркета",
                description="",
                category="",
                brand="",
                price=0,
                rating=0,
                reviews_count=0,
                article="",
                current_keywords=[],
                competitors=[],
                raw_url=url,
            )

        else:
            raise ValueError("Маркетплейс не поддерживается")


def _extract_keywords(text: str) -> list[str]:
    """Простое извлечение слов из текста как текущих ключей"""
    if not text:
        return []
    words = re.findall(r"[а-яёА-ЯЁa-zA-Z]{3,}", text.lower())
    # Убираем стоп-слова
    stop = {"для", "или", "при", "без", "под", "над", "про", "как", "это", "все",
            "его", "ваш", "наш", "нет", "так", "уже", "что", "где", "когда"}
    return list(dict.fromkeys(w for w in words if w not in stop))[:20]
