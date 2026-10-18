from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from app.agent import telegram
from app.agent.loop import AgentReply, load_history, save_messages
from app.agent.tools import ToolContext
from app.db import SessionLocal
from app.main import app


class FakeBridge:
    secret = "s3cret-token"

    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []

    async def enqueue(self, payload: dict[str, Any]) -> None:
        self.enqueued.append(payload)


class FakeAgent:
    def __init__(self, answer: str, pending_id: int | None = None) -> None:
        self.answer = AgentReply(answer, pending_id)
        self.calls: list[tuple[int, str, str]] = []
        self.presses: list[tuple[ToolContext, int, bool]] = []

    async def reply(self, context: ToolContext, text: str) -> AgentReply:
        self.calls.append((context.chat_id, context.speaker, text))
        return self.answer

    async def press(self, context: ToolContext, action_id: int, *, confirm: bool) -> AgentReply:
        self.presses.append((context, action_id, confirm))
        return AgentReply("Cancelado.", closes_buttons=True)


Sent = list[tuple[str, int | None]]


def recorder(sent: Sent) -> telegram.Reply:
    async def reply(text: str, action_id: int | None) -> None:
        sent.append((text, action_id))

    return reply


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def bridge(monkeypatch: pytest.MonkeyPatch) -> FakeBridge:
    fake = FakeBridge()
    monkeypatch.setattr(app.state, "telegram", fake, raising=False)
    return fake


UPDATE = {"update_id": 9001, "message": {"message_id": 1, "text": "hola"}}


@pytest.mark.parametrize("headers", [{}, {"X-Telegram-Bot-Api-Secret-Token": "otro"}])
async def test_webhook_rejects_a_bad_secret(
    client: httpx.AsyncClient, bridge: FakeBridge, headers: dict[str, str]
) -> None:
    response = await client.post("/telegram/webhook", json=UPDATE, headers=headers)
    assert response.status_code == 403
    assert bridge.enqueued == []


async def test_webhook_queues_each_update_once(
    client: httpx.AsyncClient, bridge: FakeBridge
) -> None:
    headers = {"X-Telegram-Bot-Api-Secret-Token": FakeBridge.secret}
    first = await client.post("/telegram/webhook", json=UPDATE, headers=headers)
    retry = await client.post("/telegram/webhook", json=UPDATE, headers=headers)
    assert (first.status_code, retry.status_code) == (200, 200)
    assert bridge.enqueued == [UPDATE]


async def test_webhook_is_off_without_telegram(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app.state, "telegram", None, raising=False)
    response = await client.post(
        "/telegram/webhook", json=UPDATE, headers={"X-Telegram-Bot-Api-Secret-Token": "x"}
    )
    assert response.status_code == 404


@pytest.mark.usefixtures("two_partners")
async def test_strangers_get_silence() -> None:
    agent = FakeAgent("hola")
    replies: Sent = []
    reply = recorder(replies)

    bot = telegram.ChatBot(agent, SessionLocal)  # type: ignore[arg-type]
    await bot.handle_text(999, 999, "dame las cuentas", reply)
    await bot.handle_start(999, reply)
    await bot.handle_new(999, 999, reply)
    assert not await bot.handle_button(999, 999, "ok:1", reply)
    assert (agent.calls, agent.presses, replies) == ([], [], [])


@pytest.mark.usefixtures("two_partners")
async def test_partners_get_the_answer_in_telegram_sized_chunks() -> None:
    agent = FakeAgent("a" * 5000, pending_id=4)
    replies: Sent = []

    bot = telegram.ChatBot(agent, SessionLocal)  # type: ignore[arg-type]
    await bot.handle_text(111, 50, "resumen", recorder(replies))
    assert agent.calls == [(50, "Socio A", "resumen")]
    assert [(len(text), action) for text, action in replies] == [(4096, None), (904, 4)]


@pytest.mark.usefixtures("two_partners")
async def test_a_button_press_reaches_the_agent_as_the_partner_who_pressed() -> None:
    agent = FakeAgent("")
    replies: Sent = []
    bot = telegram.ChatBot(agent, SessionLocal)  # type: ignore[arg-type]

    assert await bot.handle_button(222, 50, "no:9", recorder(replies))
    assert not await bot.handle_button(222, 50, "borrar:9", recorder(replies))

    [(context, action_id, confirm)] = agent.presses
    assert (context.chat_id, context.speaker, action_id, confirm) == (50, "Socio B", 9, False)
    assert replies == [("Cancelado.", None)]


def test_button_data_round_trips_and_fits_telegram() -> None:
    data = telegram.button_data(True, 123456789)
    assert telegram.parse_button(data) == (True, 123456789)
    assert len(data.encode()) <= 64
    assert telegram.parse_button("ok:") is None


@pytest.mark.usefixtures("two_partners")
async def test_nuevo_forgets_the_chat() -> None:
    async with SessionLocal() as session, session.begin():
        await save_messages(session, 50, [{"role": "user", "content": "hola"}])
    replies: Sent = []

    await telegram.ChatBot(None, SessionLocal).handle_new(222, 50, recorder(replies))
    async with SessionLocal() as session:
        assert await load_history(session, 50) == []
    assert replies == [(telegram.FORGOTTEN, None)]


def test_split_message_prefers_line_breaks() -> None:
    text = "uno\n" + "x" * 10 + "\ndos"
    assert telegram.split_message(text, limit=12) == ["uno", "x" * 10, "dos"]
    assert telegram.split_message("") == []
