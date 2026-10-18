from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from decimal import Decimal
from functools import cached_property
from zoneinfo import ZoneInfo

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.agent.options import Effort, Thinking, request_options


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
    anthropic_effort: Effort | None = None
    anthropic_thinking: Thinking = "adaptive"
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

    @field_validator("anthropic_effort", mode="before")
    @classmethod
    def blank_effort_is_default(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def thinking_fits_the_effort(self) -> "Settings":
        request_options(self.anthropic_model, self.anthropic_effort, self.anthropic_thinking)
        return self

    @property
    def model_request_options(self) -> dict[str, object]:
        return request_options(self.anthropic_model, self.anthropic_effort, self.anthropic_thinking)

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


def parse_api_keys(raw: str) -> dict[str, str]:
    keys: dict[str, str] = {}
    for entry in filter(None, (part.strip() for part in raw.split(","))):
        name, separator, key = entry.partition(":")
        if not separator or not name or not key:
            raise ValueError("API_KEYS must look like 'name:key,name:key'")
        keys[key] = name
    return keys


settings = Settings()


_frozen_today: ContextVar[date | None] = ContextVar("frozen_today", default=None)


def today() -> date:
    return _frozen_today.get() or datetime.now(ZoneInfo(settings.timezone)).date()


@contextmanager
def frozen_today(day: date) -> Iterator[None]:
    """Make today() return `day` in this context only; the evals replay fixed dates with it."""
    token = _frozen_today.set(day)
    try:
        yield
    finally:
        _frozen_today.reset(token)
