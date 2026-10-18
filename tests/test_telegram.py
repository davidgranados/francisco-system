from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from app.agent import telegram
from app.agent.loop import load_history, save_messages
from app.db import SessionLocal
from app.main import app


class FakeBridge:
    secret = "s3cret-token"

    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []

    async def enqueue(self, payload: dict[str, Any]) -> None:
        self.enqueued.append(payload)


class FakeAgent:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls: list[tuple[int, str, str]] = []

    async def reply(self, chat_id: int, speaker: str, text: str) -> str:
        self.calls.append((chat_id, speaker, text))
        return self.answer


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
    replies: list[str] = []

    async def reply(text: str) -> None:
        replies.append(text)

    bot = telegram.ChatBot(agent, SessionLocal)  # type: ignore[arg-type]
    await bot.handle_text(999, 999, "dame las cuentas", reply)
    await bot.handle_start(999, reply)
    await bot.handle_new(999, 999, reply)
    assert (agent.calls, replies) == ([], [])


@pytest.mark.usefixtures("two_partners")
async def test_partners_get_the_answer_in_telegram_sized_chunks() -> None:
    agent = FakeAgent("a" * 5000)
    replies: list[str] = []

    async def reply(text: str) -> None:
        replies.append(text)

    await telegram.ChatBot(agent, SessionLocal).handle_text(111, 50, "resumen", reply)  # type: ignore[arg-type]
    assert agent.calls == [(50, "Socio A", "resumen")]
    assert [len(chunk) for chunk in replies] == [4096, 904]


@pytest.mark.usefixtures("two_partners")
async def test_nuevo_forgets_the_chat() -> None:
    async with SessionLocal() as session, session.begin():
        await save_messages(session, 50, [{"role": "user", "content": "hola"}])
    replies: list[str] = []

    async def reply(text: str) -> None:
        replies.append(text)

    await telegram.ChatBot(None, SessionLocal).handle_new(222, 50, reply)
    async with SessionLocal() as session:
        assert await load_history(session, 50) == []
    assert replies == [telegram.FORGOTTEN]


def test_split_message_prefers_line_breaks() -> None:
    text = "uno\n" + "x" * 10 + "\ndos"
    assert telegram.split_message(text, limit=12) == ["uno", "x" * 10, "dos"]
    assert telegram.split_message("") == []
