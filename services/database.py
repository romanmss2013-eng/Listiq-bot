"""
База данных Listiq — SQLite
Таблицы: users, subscriptions, requests, referrals, payments
"""
import sqlite3
import logging
from datetime import datetime, timedelta
from contextlib import contextmanager
from config import config

logger = logging.getLogger(__name__)


def init_db():
    """Инициализация базы данных и создание таблиц"""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY,
                telegram_id     INTEGER UNIQUE NOT NULL,
                username        TEXT,
                full_name       TEXT,
                referral_code   TEXT UNIQUE,
                referred_by     INTEGER,
                free_requests   INTEGER DEFAULT 1,
                created_at      TEXT DEFAULT (datetime('now')),
                notified_expiry INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                plan            TEXT NOT NULL,
                started_at      TEXT NOT NULL,
                expires_at      TEXT NOT NULL,
                active          INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS requests (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                url             TEXT NOT NULL,
                marketplace     TEXT NOT NULL,
                result_text     TEXT,
                created_at      TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS payments (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                payment_id      TEXT UNIQUE,
                plan            TEXT NOT NULL,
                amount          INTEGER NOT NULL,
                status          TEXT DEFAULT 'pending',
                created_at      TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS referrals (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id     INTEGER NOT NULL,
                invited_id      INTEGER NOT NULL,
                bonus_given     INTEGER DEFAULT 0,
                created_at      TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (referrer_id) REFERENCES users(id),
                FOREIGN KEY (invited_id) REFERENCES users(id)
            );
        """)
    logger.info("База данных инициализирована")


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── USERS ──────────────────────────────────────────────────────────────────

def get_or_create_user(telegram_id: int, username: str = None, full_name: str = None) -> dict:
    with get_conn() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()

        if user:
            # Обновляем имя если изменилось
            if username or full_name:
                conn.execute(
                    "UPDATE users SET username=?, full_name=? WHERE telegram_id=?",
                    (username, full_name, telegram_id)
                )
            return dict(user)

        # Создаём реферальный код
        import random, string
        ref_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

        conn.execute(
            """INSERT INTO users (telegram_id, username, full_name, referral_code, free_requests)
               VALUES (?, ?, ?, ?, ?)""",
            (telegram_id, username, full_name, ref_code, config.FREE_REQUESTS)
        )
        return dict(conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone())


def get_user(telegram_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        return dict(row) if row else None


def register_referral(invited_telegram_id: int, referrer_code: str):
    """Привязываем нового пользователя к реферреру"""
    with get_conn() as conn:
        referrer = conn.execute(
            "SELECT * FROM users WHERE referral_code = ?", (referrer_code,)
        ).fetchone()
        if not referrer:
            return

        invited = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (invited_telegram_id,)
        ).fetchone()
        if not invited or invited["referred_by"]:
            return

        conn.execute(
            "UPDATE users SET referred_by = ? WHERE telegram_id = ?",
            (referrer["id"], invited_telegram_id)
        )
        conn.execute(
            "INSERT INTO referrals (referrer_id, invited_id) VALUES (?, ?)",
            (referrer["id"], invited["id"])
        )


# ── SUBSCRIPTIONS ──────────────────────────────────────────────────────────

def get_active_subscription(telegram_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT s.* FROM subscriptions s
               JOIN users u ON u.id = s.user_id
               WHERE u.telegram_id = ? AND s.active = 1
               AND s.expires_at > datetime('now')
               ORDER BY s.expires_at DESC LIMIT 1""",
            (telegram_id,)
        ).fetchone()
        return dict(row) if row else None


def create_subscription(telegram_id: int, plan: str, days: int):
    with get_conn() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if not user:
            return

        # Деактивируем старые
        conn.execute(
            "UPDATE subscriptions SET active = 0 WHERE user_id = ?", (user["id"],)
        )

        now = datetime.utcnow()
        expires = now + timedelta(days=days)
        conn.execute(
            """INSERT INTO subscriptions (user_id, plan, started_at, expires_at)
               VALUES (?, ?, ?, ?)""",
            (user["id"], plan, now.isoformat(), expires.isoformat())
        )

        # Сбрасываем флаг уведомления об истечении
        conn.execute(
            "UPDATE users SET notified_expiry = 0 WHERE telegram_id = ?",
            (telegram_id,)
        )


def add_bonus_days(telegram_id: int, days: int):
    """Добавляем бонусные дни (реферальная программа)"""
    with get_conn() as conn:
        sub = get_active_subscription(telegram_id)
        if sub:
            new_expiry = datetime.fromisoformat(sub["expires_at"]) + timedelta(days=days)
            conn.execute(
                "UPDATE subscriptions SET expires_at = ? WHERE id = ?",
                (new_expiry.isoformat(), sub["id"])
            )
        else:
            # Создаём подписку из бонуса
            create_subscription(telegram_id, "referral_bonus", days)


# ── REQUESTS ──────────────────────────────────────────────────────────────

def count_today_requests(telegram_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) as cnt FROM requests r
               JOIN users u ON u.id = r.user_id
               WHERE u.telegram_id = ?
               AND date(r.created_at) = date('now')""",
            (telegram_id,)
        ).fetchone()
        return row["cnt"] if row else 0


def save_request(telegram_id: int, url: str, marketplace: str, result: str):
    with get_conn() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if user:
            conn.execute(
                "INSERT INTO requests (user_id, url, marketplace, result_text) VALUES (?,?,?,?)",
                (user["id"], url, marketplace, result)
            )


def get_user_history(telegram_id: int, limit: int = 5) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT r.url, r.marketplace, r.created_at FROM requests r
               JOIN users u ON u.id = r.user_id
               WHERE u.telegram_id = ?
               ORDER BY r.created_at DESC LIMIT ?""",
            (telegram_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]


def use_free_request(telegram_id: int) -> bool:
    """Списывает один бесплатный запрос. Возвращает True если успешно."""
    with get_conn() as conn:
        user = conn.execute(
            "SELECT free_requests FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if user and user["free_requests"] > 0:
            conn.execute(
                "UPDATE users SET free_requests = free_requests - 1 WHERE telegram_id = ?",
                (telegram_id,)
            )
            return True
        return False


# ── PAYMENTS ──────────────────────────────────────────────────────────────

def create_payment(telegram_id: int, payment_id: str, plan: str, amount: int):
    with get_conn() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if user:
            conn.execute(
                "INSERT INTO payments (user_id, payment_id, plan, amount) VALUES (?,?,?,?)",
                (user["id"], payment_id, plan, amount)
            )


def confirm_payment(payment_id: str) -> dict | None:
    """Подтверждает платёж и возвращает данные для активации подписки"""
    with get_conn() as conn:
        payment = conn.execute(
            """SELECT p.*, u.telegram_id FROM payments p
               JOIN users u ON u.id = p.user_id
               WHERE p.payment_id = ? AND p.status = 'pending'""",
            (payment_id,)
        ).fetchone()
        if not payment:
            return None
        conn.execute(
            "UPDATE payments SET status = 'paid' WHERE payment_id = ?",
            (payment_id,)
        )
        return dict(payment)


def get_payment_by_id(payment_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM payments WHERE payment_id = ?", (payment_id,)
        ).fetchone()
        return dict(row) if row else None


def mark_payment_refunded(payment_id: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE payments SET status = 'refunded' WHERE payment_id = ?",
            (payment_id,)
        )


# ── REFERRALS ──────────────────────────────────────────────────────────────

def give_referral_bonus(invited_telegram_id: int):
    """Начисляем бонус рефереру когда приглашённый оплачивает"""
    with get_conn() as conn:
        invited = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (invited_telegram_id,)
        ).fetchone()
        if not invited or not invited["referred_by"]:
            return None

        referral = conn.execute(
            """SELECT r.*, u.telegram_id as referrer_tg
               FROM referrals r JOIN users u ON u.id = r.referrer_id
               WHERE r.invited_id = ? AND r.bonus_given = 0""",
            (invited["id"],)
        ).fetchone()

        if not referral:
            return None

        conn.execute(
            "UPDATE referrals SET bonus_given = 1 WHERE id = ?", (referral["id"],)
        )
        return referral["referrer_tg"]


# ── ADMIN / STATS ──────────────────────────────────────────────────────────

def get_stats() -> dict:
    with get_conn() as conn:
        total_users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        active_subs = conn.execute(
            "SELECT COUNT(*) as c FROM subscriptions WHERE active=1 AND expires_at > datetime('now')"
        ).fetchone()["c"]
        total_requests = conn.execute("SELECT COUNT(*) as c FROM requests").fetchone()["c"]
        revenue = conn.execute(
            "SELECT COALESCE(SUM(amount),0) as s FROM payments WHERE status='paid'"
        ).fetchone()["s"]
        return {
            "total_users": total_users,
            "active_subs": active_subs,
            "total_requests": total_requests,
            "revenue_kopecks": revenue,
        }


def get_expiring_subscriptions(in_days: int = 3) -> list:
    """Пользователи у которых подписка истекает через N дней"""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT u.telegram_id, u.full_name, s.expires_at, s.plan
               FROM subscriptions s JOIN users u ON u.id = s.user_id
               WHERE s.active = 1
               AND s.expires_at BETWEEN datetime('now') AND datetime('now', ? || ' days')
               AND u.notified_expiry = 0""",
            (str(in_days),)
        ).fetchall()
        return [dict(r) for r in rows]


def mark_expiry_notified(telegram_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET notified_expiry = 1 WHERE telegram_id = ?", (telegram_id,)
        )
