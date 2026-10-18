"""Telegram webhook: the boundary between Telegram updates and the agent."""

import logging
import secrets
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.agent.loop import Agent, clear_history
from app.db import SessionLocal
from app.models import ProcessedUpdate
from app.services import partners

logger = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4096
FAILED = "Tuve un problema para responder. Intente de nuevo en un momento."
NO_AGENT = "El asistente no está configurado todavía (falta ANTHROPIC_API_KEY)."
GREETING = (
    "Hola, {name}. Soy el asistente de las cuentas de los huevos. Dígame lo que vendió, compró "
    "o gastó, o pregúnteme por las existencias, los precios del día o el cierre. "
    "Con /nuevo empiezo una conversación desde cero."
)
FORGOTTEN = "Listo, empecemos de nuevo."

Reply = Callable[[str], Awaitable[Any]]


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    chunks: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        cut = cut if cut > 0 else limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return [*chunks, text] if text else chunks


class ChatBot:
    """What the bot does with a message, independent of python-telegram-bot."""

    def __init__(
        self, agent: Agent | None, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self.agent = agent
        self.session_factory = session_factory

    async def _partner_name(self, telegram_user_id: int) -> str | None:
        async with self.session_factory() as session:
            partner = await partners.by_telegram_id(session, telegram_user_id)
        return partner.name if partner else None

    async def handle_text(self, user_id: int, chat_id: int, text: str, reply: Reply) -> None:
        name = await self._partner_name(user_id)
        if name is None:
            return
        if self.agent is None:
            await reply(NO_AGENT)
            return
        try:
            answer = await self.agent.reply(chat_id, name, text)
        except Exception:
            logger.exception("agent failed for chat %s", chat_id)
            answer = FAILED
        for chunk in split_message(answer):
            await reply(chunk)

    async def handle_start(self, user_id: int, reply: Reply) -> None:
        name = await self._partner_name(user_id)
        if name is not None:
            await reply(GREETING.format(name=name))

    async def handle_new(self, user_id: int, chat_id: int, reply: Reply) -> None:
        if await self._partner_name(user_id) is None:
            return
        async with self.session_factory() as session, session.begin():
            await clear_history(session, chat_id)
        await reply(FORGOTTEN)


class TelegramBridge:
    def __init__(self, token: str, secret: str, bot: ChatBot) -> None:
        self.secret = secret
        self.application = Application.builder().token(token).updater(None).build()
        self.application.add_handler(CommandHandler("start", self._on_start))
        self.application.add_handler(CommandHandler("nuevo", self._on_new))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))
        self.bot = bot

    async def start(self, webhook_url: str | None) -> None:
        await self.application.initialize()
        await self.application.start()
        if webhook_url:
            await self.application.bot.set_webhook(
                url=webhook_url, secret_token=self.secret, allowed_updates=["message"]
            )
        else:
            logger.warning("PUBLIC_URL is not set: the Telegram webhook was not registered")

    async def stop(self) -> None:
        await self.application.stop()
        await self.application.shutdown()

    async def enqueue(self, payload: dict[str, Any]) -> None:
        await self.application.update_queue.put(Update.de_json(payload, self.application.bot))

    async def _on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message, user = update.effective_message, update.effective_user
        if message is None or user is None or not message.text:
            return

        async def reply(text: str) -> None:
            await message.reply_text(text)

        await context.bot.send_chat_action(message.chat_id, ChatAction.TYPING)
        await self.bot.handle_text(user.id, message.chat_id, message.text, reply)

    async def _on_start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message and update.effective_user:
            await self.bot.handle_start(
                update.effective_user.id, update.effective_message.reply_text
            )

    async def _on_new(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        message, user = update.effective_message, update.effective_user
        if message and user:
            await self.bot.handle_new(user.id, message.chat_id, message.reply_text)


class WebhookTarget(Protocol):
    """The part of TelegramBridge the webhook route needs."""

    secret: str

    async def enqueue(self, payload: dict[str, Any]) -> None: ...


router = APIRouter()


@router.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(
    request: Request,
    secret_token: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
) -> Response:
    bridge: WebhookTarget | None = getattr(request.app.state, "telegram", None)
    if bridge is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not secret_token or not secrets.compare_digest(
        secret_token.encode(), bridge.secret.encode()
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    payload = await request.json()
    update_id = payload.get("update_id") if isinstance(payload, dict) else None
    if not isinstance(update_id, int):
        return Response(status_code=status.HTTP_200_OK)
    async with SessionLocal() as session, session.begin():
        first_time = await session.scalar(
            insert(ProcessedUpdate)
            .values(update_id=update_id)
            .on_conflict_do_nothing()
            .returning(ProcessedUpdate.update_id)
        )
    if first_time is not None:
        await bridge.enqueue(payload)
    return Response(status_code=status.HTTP_200_OK)
