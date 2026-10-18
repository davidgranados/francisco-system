"""The manual tool-use loop and the per-chat conversation history."""

from typing import Any, Protocol

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.prompt import SYSTEM_PROMPT, user_turn
from app.agent.tools import dispatch, tool_definitions
from app.config import today
from app.domain.errors import DomainError
from app.models import ConversationMessage
from app.services import rates

MAX_ROUNDS = 10
HISTORY_LIMIT = 30
MAX_TOKENS = 16000
GAVE_UP = "No pude terminar esa operación. Intente de nuevo, por partes."
NO_TEXT = "No tengo una respuesta para eso."
THINKING_BLOCKS = frozenset({"thinking", "redacted_thinking"})

Message = dict[str, Any]


class MessagesAPI(Protocol):
    async def create(self, **kwargs: Any) -> Any: ...


class AnthropicLike(Protocol):
    @property
    def messages(self) -> MessagesAPI: ...


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
    ) -> None:
        self.client = client
        self.model = model
        self.session_factory = session_factory
        self.system = [
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
        ]
        self.tools = tool_definitions()

    async def reply(self, chat_id: int, speaker: str, text: str) -> str:
        async with self.session_factory() as session, session.begin():
            history = await load_history(session, chat_id)
            rate = await _rate_text(session)
        turn: list[Message] = [{"role": "user", "content": user_turn(text, today(), rate, speaker)}]
        answer = await self._run(history, turn)
        async with self.session_factory() as session, session.begin():
            await save_messages(session, chat_id, turn)
        return answer

    async def _run(self, history: list[Message], turn: list[Message]) -> str:
        for _ in range(MAX_ROUNDS):
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=self.system,
                tools=self.tools,
                messages=[*history, *turn],
            )
            turn.append(
                {"role": "assistant", "content": [block.to_dict() for block in response.content]}
            )
            if response.stop_reason != "tool_use":
                return _text_of(response.content) or NO_TEXT
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                outcome = await dispatch(block.name, block.input, self.session_factory)
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
        return GAVE_UP
