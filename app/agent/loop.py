"""The manual tool-use loop and the per-chat conversation history."""

import json
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent import pending
from app.agent.options import request_options
from app.agent.prompt import SYSTEM_PROMPT, user_turn
from app.agent.tools import ToolContext, dispatch, resolve_pending, tool_definitions
from app.config import today
from app.domain.errors import DomainError
from app.models import ConversationMessage
from app.services import rates

MAX_ROUNDS = 10
HISTORY_LIMIT = 30
MAX_TOKENS = 16000
GAVE_UP = "No pude terminar esa operación. Intente de nuevo, por partes."
NO_TEXT = "No tengo una respuesta para eso."
REFUSED = "No puedo ayudar con eso. Si es una cuenta del negocio, dígamela de otra forma."
THINKING_BLOCKS = frozenset({"thinking", "redacted_thinking"})
CONFIRMED_NOTE = (
    "[Botón Confirmar] Se ejecutó {tool}. Resultado: {result}\n"
    "Dile al socio en pocas líneas qué quedó guardado y sigue con lo que faltaba, si faltaba algo."
)
BUTTON_NOTE = "[Botón {button}] {tool}"

Message = dict[str, Any]


class MessagesAPI(Protocol):
    async def create(self, **kwargs: Any) -> Any: ...


class AnthropicLike(Protocol):
    @property
    def messages(self) -> MessagesAPI: ...


@dataclass(frozen=True)
class AgentReply:
    text: str
    pending_id: int | None = None
    """The action waiting for Confirmar/Cancelar under this reply, if the model prepared one."""
    closes_buttons: bool = False
    """True when a pressed button's action is done with, so its buttons can go."""


async def load_history(session: AsyncSession, chat_id: int) -> list[Message]:
    rows = list(
        await session.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.chat_id == chat_id)
            .order_by(ConversationMessage.id.desc())
            .limit(HISTORY_LIMIT)
        )
    )
    history = [{"role": row.role, "content": row.content} for row in reversed(rows)]
    # A window can open on a tool_result whose tool_use was cut off; start at a typed message.
    while history and not (history[0]["role"] == "user" and isinstance(history[0]["content"], str)):
        history.pop(0)
    return history


def _for_storage(message: Message) -> Message | None:
    """Drop thinking blocks: the history window gets trimmed, which would invalidate them."""
    content = message["content"]
    if isinstance(content, str):
        return message
    kept = [block for block in content if block.get("type") not in THINKING_BLOCKS]
    return {"role": message["role"], "content": kept} if kept else None


async def save_messages(session: AsyncSession, chat_id: int, messages: list[Message]) -> None:
    for message in filter(None, map(_for_storage, messages)):
        session.add(
            ConversationMessage(chat_id=chat_id, role=message["role"], content=message["content"])
        )
    await session.flush()


async def clear_history(session: AsyncSession, chat_id: int) -> None:
    await session.execute(delete(ConversationMessage).where(ConversationMessage.chat_id == chat_id))


async def _rate_text(session: AsyncSession) -> str:
    try:
        return rates.describe(await rates.rate_for(session, today()))
    except DomainError:
        return "sin tasa guardada"


def _text_of(content: list[Any]) -> str:
    return "\n".join(block.text for block in content if block.type == "text").strip()


class Agent:
    def __init__(
        self,
        client: AnthropicLike,
        model: str,
        session_factory: async_sessionmaker[AsyncSession],
        options: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.session_factory = session_factory
        self.options = request_options(model) if options is None else options
        self.system = [
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
        ]
        self.tools = tool_definitions()

    async def reply(self, context: ToolContext, text: str) -> AgentReply:
        async with self.session_factory() as session, session.begin():
            history = await load_history(session, context.chat_id)
            rate = await _rate_text(session)
        turn: list[Message] = [
            {"role": "user", "content": user_turn(text, today(), rate, context.speaker)}
        ]
        answer = await self._run(history, turn, context)
        async with self.session_factory() as session, session.begin():
            await save_messages(session, context.chat_id, turn)
        return answer

    async def press(self, context: ToolContext, action_id: int, *, confirm: bool) -> AgentReply:
        """A Confirmar or Cancelar press: the code acts, then the model reports a success."""
        resolution = await resolve_pending(
            self.session_factory, action_id, context, confirm=confirm
        )
        if resolution.outcome == pending.Outcome.CONFIRMED:
            result = json.dumps(resolution.result, ensure_ascii=False)
            report = await self.reply(
                context, CONFIRMED_NOTE.format(tool=resolution.tool, result=result)
            )
            return AgentReply(report.text, report.pending_id, closes_buttons=True)
        if resolution.outcome is not None:
            button = "Confirmar" if confirm else "Cancelar"
            note = BUTTON_NOTE.format(button=button, tool=resolution.tool)
            async with self.session_factory() as session, session.begin():
                await save_messages(
                    session,
                    context.chat_id,
                    [
                        {"role": "user", "content": note},
                        {
                            "role": "assistant",
                            "content": [{"type": "text", "text": resolution.message}],
                        },
                    ],
                )
        return AgentReply(resolution.message, closes_buttons=resolution.final)

    async def _run(
        self, history: list[Message], turn: list[Message], context: ToolContext
    ) -> AgentReply:
        pending_id: int | None = None
        for _ in range(MAX_ROUNDS):
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=self.system,
                tools=self.tools,
                messages=[*history, *turn],
                **self.options,
            )
            turn.append(
                {"role": "assistant", "content": [block.to_dict() for block in response.content]}
            )
            if response.stop_reason == "refusal":
                return AgentReply(REFUSED, pending_id)
            if response.stop_reason != "tool_use":
                return AgentReply(_text_of(response.content) or NO_TEXT, pending_id)
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                outcome = await dispatch(block.name, block.input, self.session_factory, context)
                pending_id = outcome.pending_id or pending_id
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": outcome.content,
                        "is_error": outcome.is_error,
                    }
                )
            turn.append({"role": "user", "content": results})
        turn.append({"role": "assistant", "content": [{"type": "text", "text": GAVE_UP}]})
        return AgentReply(GAVE_UP, pending_id)
