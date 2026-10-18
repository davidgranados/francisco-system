import copy
import json
from datetime import timedelta
from decimal import Decimal as D
from typing import Any

import pytest
from anthropic.types import Message, TextBlock, ThinkingBlock, ToolUseBlock, Usage

from app.agent import loop, pending, tools
from app.agent.loop import Agent
from app.agent.options import request_options
from app.agent.tools import ToolContext
from app.config import today
from app.db import SessionLocal
from app.domain.types import PaymentMethod
from app.models import PendingAction
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


SOCIOS = {"que": "socios"}
CHAT = ToolContext(chat_id=7, partner_id=1, speaker="Socio A")
OTHER_PARTNER = ToolContext(chat_id=7, partner_id=2, speaker="Socio B")
NO_EGGS = {"cajas": 0, "cartones": 0, "medios": 0, "sueltos": 0}


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
    client = FakeAnthropic(use("consultar", {"que": "existencias"}), final("Quedan 360 huevos."))
    agent = Agent(client, "claude-sonnet-5-5", SessionLocal)

    answer = await agent.reply(CHAT, "¿cuántos huevos quedan?")

    assert answer.text == "Quedan 360 huevos."
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
        use("registrar_venta", {**NO_EGGS, "cartones": 1, "forma_pago": "punto"}),
        final("No hay huevos."),
    )
    await Agent(client, "m", SessionLocal).reply(CHAT, "vendí un cartón por punto")
    [result] = tool_results(client.messages.calls[1])
    assert result["is_error"] is True
    assert result["content"] == "No hay huevos en existencia. Primero registre una compra."


@pytest.mark.parametrize(
    ("name", "arguments", "message"),
    [
        ("registrar_venta", {**NO_EGGS, "cartones": 1, "forma_pago": "trueque"}, "Datos inválidos"),
        ("registrar_venta", {**NO_EGGS, "forma_pago": "punto"}, "al menos un huevo"),
        ("borrar_todo", {}, "No existe la herramienta"),
    ],
)
async def test_bad_tool_calls_are_errors_for_the_model(
    name: str, arguments: dict[str, Any], message: str
) -> None:
    client = FakeAnthropic(use(name, arguments), final("ok"))
    await Agent(client, "m", SessionLocal).reply(CHAT, "hola")
    [result] = tool_results(client.messages.calls[1])
    assert result["is_error"] is True
    assert message in result["content"]


async def _prepare_close(call: Call) -> tuple[Agent, FakeAnthropic, int]:
    await call(
        expenses.record_expense, expenses.ExpenseInput(concept="Bolsas", amount_usd=D("0.40"))
    )
    client = FakeAnthropic(
        use("preparar_cierre", {"reserva": "0"}),
        final("Gastos $ 0,40. Toque Confirmar."),
        final("Listo, cierre guardado."),
    )
    agent = Agent(client, "m", SessionLocal)
    answer = await agent.reply(CHAT, "haz el cierre")
    assert answer.pending_id is not None
    return agent, client, answer.pending_id


@pytest.mark.usefixtures("two_partners")
async def test_a_close_waits_for_the_button_and_runs_once(call: Call) -> None:
    agent, client, action_id = await _prepare_close(call)
    [preview] = tool_results(client.messages.calls[1])
    assert json.loads(preview["content"])["vista_previa"]["expenses_usd"] == "0.40"
    assert await call(settlements.list_settlements) == []

    done = await agent.press(CHAT, action_id, confirm=True)

    assert (done.text, done.closes_buttons) == ("Listo, cierre guardado.", True)
    [settlement] = await call(settlements.list_settlements)
    assert settlement.expenses_usd == D("0.40")
    note = client.messages.calls[2]["messages"][-1]["content"]
    assert "[Botón Confirmar] Se ejecutó preparar_cierre" in note
    again = await agent.press(CHAT, action_id, confirm=True)
    assert again.text == pending.USED
    assert len(await call(settlements.list_settlements)) == 1


@pytest.mark.usefixtures("two_partners")
async def test_only_the_partner_who_asked_can_press(call: Call) -> None:
    agent, _, action_id = await _prepare_close(call)
    refused = await agent.press(OTHER_PARTNER, action_id, confirm=True)
    assert (refused.text, refused.closes_buttons) == (pending.NOT_YOURS, False)
    cancelled = await agent.press(CHAT, action_id, confirm=False)
    assert (cancelled.text, cancelled.closes_buttons) == (tools.CANCELLED, True)
    assert await call(settlements.list_settlements) == []
    assert (await _history(7))[-1]["content"] == [{"type": "text", "text": tools.CANCELLED}]


@pytest.mark.usefixtures("two_partners")
async def test_a_preview_overtaken_by_new_data_is_not_executed(call: Call) -> None:
    agent, _, action_id = await _prepare_close(call)
    await call(
        expenses.record_expense, expenses.ExpenseInput(concept="Hielo", amount_usd=D("1.00"))
    )
    changed = await agent.press(CHAT, action_id, confirm=True)
    assert changed.text == tools.CHANGED
    assert await call(settlements.list_settlements) == []


@pytest.mark.usefixtures("two_partners")
async def test_an_expired_or_superseded_preview_is_refused(call: Call) -> None:
    agent, _, first = await _prepare_close(call)
    _, _, second = await _prepare_close(call)
    assert (await agent.press(CHAT, first, confirm=True)).text == pending.USED
    async with SessionLocal() as session, session.begin():
        action = await session.get(PendingAction, second)
        assert action is not None
        action.expires_at = pending.now() - timedelta(seconds=1)
    assert (await agent.press(CHAT, second, confirm=True)).text == pending.EXPIRED
    assert await call(settlements.list_settlements) == []


def test_no_tool_takes_a_confirmation_flag() -> None:
    for definition in tools.tool_definitions():
        assert "confirmado" not in definition["input_schema"]["properties"]
    confirming = {tool.name for tool in tools.TOOLS if tool.kind == tools.ToolKind.CONFIRM}
    assert confirming == {"preparar_cierre", "preparar_anulacion"}


async def test_history_carries_over_without_thinking_blocks() -> None:
    thinking = ThinkingBlock(type="thinking", thinking="", signature="firma")
    tool_turn = _message(
        [thinking, ToolUseBlock(type="tool_use", id="t1", name="consultar", input=SOCIOS)],
        "tool_use",
    )
    client = FakeAnthropic(tool_turn, final("Sin socios."), final("De nada."))
    agent = Agent(client, "m", SessionLocal)
    await agent.reply(CHAT, "¿quiénes son los socios?")
    await agent.reply(CHAT, "gracias")

    within_turn = client.messages.calls[1]["messages"][1]["content"]
    assert within_turn[0] == {"type": "thinking", "thinking": "", "signature": "firma"}
    next_turn = client.messages.calls[2]["messages"]
    assert [m["role"] for m in next_turn] == ["user", "assistant", "user", "assistant", "user"]
    assert all(b["type"] != "thinking" for m in next_turn[1:2] for b in m["content"])
    assert next_turn[-1]["content"].endswith("gracias")


async def test_the_loop_stops_after_ten_rounds() -> None:
    client = FakeAnthropic(*(use("consultar", SOCIOS, f"t{i}") for i in range(10)))
    answer = await Agent(client, "m", SessionLocal).reply(CHAT, "hola")
    assert answer.text == loop.GAVE_UP
    assert len(client.messages.calls) == 10
    assert (await _history(7))[-1]["content"] == [{"type": "text", "text": loop.GAVE_UP}]


def test_every_request_names_its_thinking_and_effort() -> None:
    assert request_options("claude-haiku-5-5") == {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "medium"},
    }
    assert request_options("claude-sonnet-5-5", "low", "off")["thinking"] == {
        "type": "between_tools"
    }
    assert request_options("claude-haiku-5-5", "high", "off")["thinking"] == {"type": "disabled"}
    with pytest.raises(ValueError, match="thinking off"):
        request_options("claude-haiku-5-5", "max", "off")


async def test_the_agent_sends_the_options_and_handles_a_refusal() -> None:
    refusal = _message([], "refusal")
    client = FakeAnthropic(refusal)
    agent = Agent(client, "claude-haiku-5-5", SessionLocal)
    answer = await agent.reply(CHAT, "algo raro")
    [sent] = client.messages.calls
    assert (sent["thinking"], sent["output_config"]) == (
        {"type": "adaptive"},
        {"effort": "medium"},
    )
    assert answer.text == loop.REFUSED
    assert [m["role"] for m in await _history(7)] == ["user"]
