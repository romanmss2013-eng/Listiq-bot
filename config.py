import os
from dataclasses import dataclass, field

@dataclass
class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    YUKASSA_SHOP_ID: str = os.getenv("YUKASSA_SHOP_ID", "")
    YUKASSA_SECRET_KEY: str = os.getenv("YUKASSA_SECRET_KEY", "")
    DB_PATH: str = os.getenv("DB_PATH", "listiq.db")
    DAILY_REQUEST_LIMIT: int = 100
    FREE_REQUESTS: int = 1
    REFERRAL_BONUS_DAYS: int = 7
    PRICE_MONTH: int = 149000
    PRICE_6MONTHS: int = 799000
    PRICE_YEAR: int = 1299000
    DAYS_MONTH: int = 30
    DAYS_6MONTHS: int = 180
    DAYS_YEAR: int = 365
    NOTIFY_BEFORE_DAYS: int = 3
    ADMIN_IDS: list = field(default_factory=list)

    def __post_init__(self):
        admin_env = os.getenv("ADMIN_IDS", "7130117291")
        self.ADMIN_IDS = [int(x) for x in admin_env.split(",") if x.strip()]

config = Config()
