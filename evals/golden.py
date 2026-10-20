"""A scripted stand-in for the API that answers each case the way the case expects.

Running every case with it proves two things without the network: the harness drives and
scores a conversation end to end, and each case's expected state is what its expected calls
actually produce through the real services.
"""

from collections import defaultdict
from typing import Any

from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

from evals.cases import Case, Mention

# Arguments the cases leave out because they are 0 or obvious; added only to make the call.
DEFAULT_ARGS: dict[str, dict[str, Any]] = {
    "registrar_venta": {"cajas": 0, "cartones": 0, "medios": 0, "sueltos": 0},
    "registrar_merma": {"cartones": 0, "medios": 0, "sueltos": 0},
    "registrar_conteo": {"cajas": 0, "cartones": 0, "medios": 0, "sueltos": 0},
    "registrar_gasto": {"pagado_por": "negocio", "moneda": "usd"},
    "preparar_cierre": {"reserva": "0"},
    "preparar_anulacion": {"motivo": "error al anotar"},
    "marcar_gasto_devuelto": {"gasto_id": 0, "socio": ""},
    "mover_dinero": {"socio": ""},
}


def _first(value: Any) -> Any:
    """The first alternative, as the value itself ("~transporte" means Transporte)."""
    value = value[0] if isinstance(value, list) else value
    return value[1:] if isinstance(value, str) and value.startswith("~") else value


def _text(mentions: list[Mention]) -> str:
    return " ".join(_first(m) for m in mentions) or "Listo."


def message(content: list[Any], stop_reason: str) -> Message:
    return Message(
        id="msg_golden",
        content=content,
        model="golden",
        role="assistant",
        stop_reason=stop_reason,
        stop_sequence=None,
        type="message",
        usage=Usage(input_tokens=0, output_tokens=0),
    )


def script(case: Case) -> dict[int, list[Message]]:
    """Per turn: one response with every expected call, then the reply with the mentions."""
    turns: dict[int, list[Message]] = defaultdict(list)
    for index, turn in enumerate(case.turnos):
        if turn.llamadas:
            uses = [
                ToolUseBlock(
                    type="tool_use",
                    id=f"toolu_{index}_{n}",
                    name=call.herramienta,
                    input={
                        **DEFAULT_ARGS.get(call.herramienta, {}),
                        **{key: _first(value) for key, value in call.args.items()},
                    },
                )
                for n, call in enumerate(turn.llamadas)
            ]
            turns[index].append(message(uses, "tool_use"))
        turns[index].append(
            message([TextBlock(type="text", text=_text(turn.menciona))], "end_turn")
        )
    return turns


class _Messages:
    def __init__(self, client: "GoldenClient") -> None:
        self.client = client

    async def create(self, **_: Any) -> Message:
        queue = self.client.turns.get(self.client.turn, [])
        if not queue:
            return message([TextBlock(type="text", text="Listo.")], "end_turn")
        return queue.pop(0)


class GoldenClient:
    def __init__(self, case: Case) -> None:
        self.turns = script(case)
        self.turn = 0
        self.messages = _Messages(self)

    def begin_turn(self, index: int) -> None:
        self.turn = index
