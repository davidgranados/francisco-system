from datetime import date, datetime
from decimal import Decimal
from functools import cached_property
from zoneinfo import ZoneInfo

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://francisco:francisco@localhost:5432/francisco"
    api_keys: str = ""
    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    public_url: str | None = None
    railway_public_domain: str | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    markup: Decimal = Decimal("0.25")
    timezone: str = "America/Caracas"
    bcv_api_url: str = "https://ve.dolarapi.com/v1/dolares/oficial"

    @field_validator(
        "telegram_bot_token",
        "telegram_webhook_secret",
        "public_url",
        "railway_public_domain",
        "anthropic_api_key",
        mode="before",
    )
    @classmethod
    def blank_is_unset(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("database_url")
    @classmethod
    def use_asyncpg(cls, value: str) -> str:
        for prefix in ("postgresql://", "postgres://"):
            if value.startswith(prefix):
                return "postgresql+asyncpg://" + value.removeprefix(prefix)
        return value

    @field_validator("api_keys")
    @classmethod
    def api_keys_are_name_key_pairs(cls, value: str) -> str:
        parse_api_keys(value)
        return value

    @field_validator("timezone")
    @classmethod
    def timezone_exists(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @cached_property
    def api_key_map(self) -> dict[str, str]:
        """API key to the name of who holds it."""
        return parse_api_keys(self.api_keys)

    @property
    def webhook_url(self) -> str | None:
        base = self.public_url or (
            f"https://{self.railway_public_domain}" if self.railway_public_domain else None
        )
        return f"{base.rstrip('/')}/telegram/webhook" if base else None

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_webhook_secret)


def parse_api_keys(raw: str) -> dict[str, str]:
    keys: dict[str, str] = {}
    for entry in filter(None, (part.strip() for part in raw.split(","))):
        name, separator, key = entry.partition(":")
        if not separator or not name or not key:
            raise ValueError("API_KEYS must look like 'name:key,name:key'")
        keys[key] = name
    return keys


settings = Settings()


def today() -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()
