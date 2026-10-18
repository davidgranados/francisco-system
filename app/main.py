import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from anthropic import AsyncAnthropic
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.agent import telegram
from app.agent.loop import Agent
from app.api.v1 import router as v1_router
from app.config import settings
from app.db import SessionLocal, engine
from app.domain.errors import DomainError

logger = logging.getLogger(__name__)


async def start_telegram() -> telegram.TelegramBridge | None:
    if not (settings.telegram_bot_token and settings.telegram_webhook_secret):
        logger.info("Telegram is disabled: TELEGRAM_BOT_TOKEN or TELEGRAM_WEBHOOK_SECRET missing")
        return None
    agent = (
        Agent(
            AsyncAnthropic(api_key=settings.anthropic_api_key),
            settings.anthropic_model,
            SessionLocal,
        )
        if settings.anthropic_api_key
        else None
    )
    bridge = telegram.TelegramBridge(
        settings.telegram_bot_token,
        settings.telegram_webhook_secret,
        telegram.ChatBot(agent, SessionLocal),
    )
    try:
        await bridge.start(settings.webhook_url)
    except Exception:
        # The API keeps serving when Telegram rejects the token or is unreachable.
        logger.exception("Telegram failed to start; the bot stays off")
        return None
    return bridge


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    bridge = await start_telegram()
    app.state.telegram = bridge
    try:
        yield
    finally:
        if bridge is not None:
            await bridge.stop()
        await engine.dispose()


app = FastAPI(
    title="Francisco System", description="Cuentas del negocio de huevos.", lifespan=lifespan
)
app.include_router(v1_router)
app.include_router(telegram.router)


@app.exception_handler(DomainError)
async def domain_error(_: Request, error: DomainError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": error.message})


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return {"status": "ok"}
