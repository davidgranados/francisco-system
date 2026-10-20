"""Telegram webhook: the boundary between Telegram updates and the agent."""

import logging
import secrets
from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.agent import identity
from app.agent.identity import Actor
from app.agent.loop import Agent, AgentReply, clear_history
from app.agent.tools import ToolContext
from app.config import DevUser, settings
from app.db import SessionLocal
from app.models import ProcessedUpdate

logger = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4096
NO_TEXT_REPLY = "Listo."
FAILED = "Tuve un problema para responder. Intente de nuevo en un momento."
NO_AGENT = "El asistente no está configurado todavía (falta ANTHROPIC_API_KEY)."
GREETING = (
    "Hola, {name}. Soy el asistente de las cuentas de los huevos. Dígame lo que vendió, compró "
    "o gastó, o pregúnteme por las existencias, los precios del día o el cierre. "
    "Con /nuevo empiezo una conversación desde cero."
)
FORGOTTEN = "Listo, empecemos de nuevo."
CONFIRM, CANCEL = "ok", "no"

Reply = Callable[[str, int | None], Awaitable[Any]]
"""Send one message; the int, when given, is the pending action whose buttons go under it."""


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
        self,
        agent: Agent | None,
        session_factory: async_sessionmaker[AsyncSession],
        dev_users: Sequence[DevUser] | None = None,
    ) -> None:
        self.agent = agent
        self.session_factory = session_factory
        self.dev_users = settings.dev_users if dev_users is None else dev_users

    async def _actor(self, telegram_user_id: int) -> Actor | None:
        async with self.session_factory() as session:
            return await identity.resolve(session, telegram_user_id, self.dev_users)

    async def _context(self, user_id: int, chat_id: int) -> ToolContext | None:
        actor = await self._actor(user_id)
        if actor is None:
            return None
        if not actor.is_partner:
            logger.info("developer %s wrote in chat %s", actor.name, chat_id)
        return ToolContext(chat_id=chat_id, actor=actor)

    async def _send(self, answer: AgentReply, reply: Reply) -> None:
        chunks = split_message(answer.text) or [NO_TEXT_REPLY]
        for index, chunk in enumerate(chunks):
            await reply(chunk, answer.pending_id if index == len(chunks) - 1 else None)

    async def handle_text(self, user_id: int, chat_id: int, text: str, reply: Reply) -> None:
        context = await self._context(user_id, chat_id)
        if context is None:
            return
        if self.agent is None:
            await reply(NO_AGENT, None)
            return
        try:
            answer = await self.agent.reply(context, text)
        except Exception:
            logger.exception("agent failed for chat %s", chat_id)
            answer = AgentReply(FAILED)
        await self._send(answer, reply)

    async def handle_button(self, user_id: int, chat_id: int, data: str, reply: Reply) -> bool:
        """Confirm or cancel a pending action. True when its buttons should be removed."""
        context = await self._context(user_id, chat_id)
        button = parse_button(data)
        if context is None or button is None or self.agent is None:
            return False
        confirm, action_id = button
        try:
            answer = await self.agent.press(context, action_id, confirm=confirm)
        except Exception:
            logger.exception("button failed for chat %s", chat_id)
            answer = AgentReply(FAILED)
        await self._send(answer, reply)
        return answer.closes_buttons

    async def handle_start(self, user_id: int, reply: Reply) -> None:
        actor = await self._actor(user_id)
        if actor is not None:
            await reply(GREETING.format(name=actor.name), None)

    async def handle_new(self, user_id: int, chat_id: int, reply: Reply) -> None:
        if await self._actor(user_id) is None:
            return
        async with self.session_factory() as session, session.begin():
            await clear_history(session, chat_id)
        await reply(FORGOTTEN, None)


def button_data(confirm: bool, action_id: int) -> str:
    return f"{CONFIRM if confirm else CANCEL}:{action_id}"


def parse_button(data: str) -> tuple[bool, int] | None:
    kind, _, number = data.partition(":")
    if kind not in (CONFIRM, CANCEL) or not number.isdigit():
        return None
    return kind == CONFIRM, int(number)


def confirmation_keyboard(action_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Confirmar", callback_data=button_data(True, action_id)),
                InlineKeyboardButton("Cancelar", callback_data=button_data(False, action_id)),
            ]
        ]
    )


class TelegramBridge:
    def __init__(self, token: str, secret: str, bot: ChatBot) -> None:
        self.secret = secret
        self.application = Application.builder().token(token).updater(None).build()
        self.application.add_handler(CommandHandler("start", self._on_start))
        self.application.add_handler(CommandHandler("nuevo", self._on_new))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))
        self.application.add_handler(CallbackQueryHandler(self._on_button))
        self.bot = bot

    async def start(self, webhook_url: str | None) -> None:
        await self.application.initialize()
        await self.application.start()
        if webhook_url:
            await self.application.bot.set_webhook(
                url=webhook_url,
                secret_token=self.secret,
                allowed_updates=["message", "callback_query"],
            )
        else:
            logger.warning("PUBLIC_URL is not set: the Telegram webhook was not registered")

    async def stop(self) -> None:
        await self.application.stop()
        await self.application.shutdown()

    async def send_message(self, chat_id: int, text: str) -> None:
        await self.application.bot.send_message(chat_id, text)

    async def enqueue(self, payload: dict[str, Any]) -> None:
        await self.application.update_queue.put(Update.de_json(payload, self.application.bot))

    async def _on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message, user = update.effective_message, update.effective_user
        if message is None or user is None or not message.text:
            return
        await context.bot.send_chat_action(message.chat_id, ChatAction.TYPING)
        await self.bot.handle_text(user.id, message.chat_id, message.text, _replier(message))

    async def _on_button(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        query, user = update.callback_query, update.effective_user
        if query is None or user is None or query.data is None:
            return
        await query.answer()
        message = query.message
        if not isinstance(message, Message):
            return
        if await self.bot.handle_button(user.id, message.chat_id, query.data, _replier(message)):
            await query.edit_message_reply_markup(reply_markup=None)

    async def _on_start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message and update.effective_user:
            await self.bot.handle_start(
                update.effective_user.id, _replier(update.effective_message)
            )

    async def _on_new(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        message, user = update.effective_message, update.effective_user
        if message and user:
            await self.bot.handle_new(user.id, message.chat_id, _replier(message))


def _replier(message: Message) -> Reply:
    async def reply(text: str, action_id: int | None) -> None:
        markup = confirmation_keyboard(action_id) if action_id is not None else None
        await message.reply_text(text, reply_markup=markup)

    return reply


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
