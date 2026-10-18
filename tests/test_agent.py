import copy
import json
from decimal import Decimal as D
from typing import Any

import pytest
from anthropic.types import Message, TextBlock, ThinkingBlock, ToolUseBlock, Usage

from app.agent import loop, tools
from app.agent.loop import Agent
from app.config import today
from app.db import SessionLocal
from app.domain.types import PaymentMethod
from app.services import expenses, purchases, rates, settlements
from tests.conftest import Call


class FakeMessages:
    def __init__(self, script: list[Message]) -> None:
        self.script = script
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Message:
        self.calls.append(copy.deepcopy(kwargs))
        return self.script.pop(0)


class FakeAnthropic:
    def __init__(self, *script: Message) -> None:
        self.messages = FakeMessages(list(script))


def _message(content: list[Any], stop_reason: str) -> Message:
    return Message(
        id="msg",
        content=content,
        model="claude-sonnet-5-5",
        role="assistant",
        stop_reason=stop_reason,
        stop_sequence=None,
        type="message",
        usage=Usage(input_tokens=1, output_tokens=1),
    )


def use(name: str, arguments: dict[str, Any], call_id: str = "t1") -> Message:
    return _message(
        [ToolUseBlock(type="tool_use", id=call_id, name=name, input=arguments)], "tool_use"
    )


def final(text: str) -> Message:
    return _message([TextBlock(type="text", text=text)], "end_turn")


def tool_results(call: dict[str, Any]) -> list[dict[str, Any]]:
    return call["messages"][-1]["content"]


@pytest.fixture(autouse=True)
async def todays_rate(call: Call) -> None:
    await call(rates.set_rate, rates.SetRateInput(day=today(), rate=D("880.00")))


async def _history(chat_id: int) -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        return await loop.load_history(session, chat_id)


async def test_the_loop_runs_a_tool_and_returns_the_final_text(call: Call) -> None:
    await call(
        purchases.register_purchase,
        purchases.PurchaseInput(
            box_count=1, cost_per_box_usd=D("60.00"), payment_method=PaymentMethod.CASH_USD
        ),
    )
    client = FakeAnthropic(use("ver_existencias", {}), final("Quedan 360 huevos."))
    agent = Agent(client, "claude-sonnet-5-5", SessionLocal)

    answer = await agent.reply(7, "Socio A", "¿cuántos huevos quedan?")

    assert answer == "Quedan 360 huevos."
    first, second = client.messages.calls
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert first["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert {tool["name"] for tool in first["tools"]} == set(tools.REGISTRY)
    opening = first["messages"][0]["content"]
    assert opening.startswith("[Hoy: ")
    assert "Bs 880,0000" in opening
    assert "Escribe: Socio A]" in opening
    [result] = tool_results(second)
    assert (result["tool_use_id"], result["is_error"]) == ("t1", False)
    assert json.loads(result["content"])["total_eggs"] == 360
    assert [m["role"] for m in await _history(7)] == ["user", "assistant", "user", "assistant"]


async def test_a_domain_error_goes_back_to_the_model_as_is_error() -> None:
    client = FakeAnthropic(
        use("registrar_venta", {"cartons": 1, "payment_method": "punto"}), final("No hay huevos.")
    )
    await Agent(client, "m", SessionLocal).reply(7, "Socio A", "vendí un cartón por punto")
    [result] = tool_results(client.messages.calls[1])
    assert result["is_error"] is True
    assert result["content"] == "No hay huevos en existencia. Primero registre una compra."


@pytest.mark.parametrize(
    ("name", "arguments", "message"),
    [
        ("registrar_venta", {"cartons": 1, "payment_method": "trueque"}, "Datos inválidos"),
        ("registrar_venta", {"payment_method": "punto"}, "al menos un huevo"),
        ("borrar_todo", {}, "No existe la herramienta"),
    ],
)
async def test_bad_tool_calls_are_errors_for_the_model(
    name: str, arguments: dict[str, Any], message: str
) -> None:
    client = FakeAnthropic(use(name, arguments), final("ok"))
    await Agent(client, "m", SessionLocal).reply(7, "Socio A", "hola")
    [result] = tool_results(client.messages.calls[1])
    assert result["is_error"] is True
    assert message in result["content"]


@pytest.mark.usefixtures("two_partners")
async def test_ejecutar_cierre_needs_confirmado(call: Call) -> None:
    await call(
        expenses.record_expense, expenses.ExpenseInput(concept="Bolsas", amount_usd=D("0.40"))
    )
    unconfirmed = FakeAnthropic(use("ejecutar_cierre", {}), final("¿Confirma?"))
    await Agent(unconfirmed, "m", SessionLocal).reply(7, "Socio A", "haz el cierre")
    [refused] = tool_results(unconfirmed.messages.calls[1])
    assert (refused["is_error"], refused["content"]) == (True, tools.CONFIRMATION_REQUIRED)
    assert await call(settlements.list_settlements) == []

    confirmed = FakeAnthropic(use("ejecutar_cierre", {"confirmado": True}), final("Listo."))
    await Agent(confirmed, "m", SessionLocal).reply(7, "Socio A", "sí, confirmo")
    [done] = tool_results(confirmed.messages.calls[1])
    assert done["is_error"] is False
    [settlement] = await call(settlements.list_settlements)
    assert settlement.expenses_usd == D("0.40")


def test_confirmation_tools_show_confirmado_in_their_schema() -> None:
    for name in ("ejecutar_cierre", "anular_venta", "anular_compra"):
        tool = tools.REGISTRY[name]
        assert tool.requires_confirmation
        assert "confirmado" in tool.definition()["input_schema"]["properties"]


async def test_history_carries_over_without_thinking_blocks() -> None:
    thinking = ThinkingBlock(type="thinking", thinking="", signature="firma")
    tool_turn = _message(
        [thinking, ToolUseBlock(type="tool_use", id="t1", name="ver_socios", input={})], "tool_use"
    )
    client = FakeAnthropic(tool_turn, final("Sin socios."), final("De nada."))
    agent = Agent(client, "m", SessionLocal)
    await agent.reply(7, "Socio A", "¿quiénes son los socios?")
    await agent.reply(7, "Socio A", "gracias")

    within_turn = client.messages.calls[1]["messages"][1]["content"]
    assert within_turn[0] == {"type": "thinking", "thinking": "", "signature": "firma"}
    next_turn = client.messages.calls[2]["messages"]
    assert [m["role"] for m in next_turn] == ["user", "assistant", "user", "assistant", "user"]
    assert all(b["type"] != "thinking" for m in next_turn[1:2] for b in m["content"])
    assert next_turn[-1]["content"].endswith("gracias")


async def test_the_loop_stops_after_ten_rounds() -> None:
    client = FakeAnthropic(*(use("ver_socios", {}, f"t{i}") for i in range(10)))
    answer = await Agent(client, "m", SessionLocal).reply(7, "Socio A", "hola")
    assert answer == loop.GAVE_UP
    assert len(client.messages.calls) == 10
    assert (await _history(7))[-1]["content"] == [{"type": "text", "text": loop.GAVE_UP}]
