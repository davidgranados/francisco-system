"""The eval set and its runner, proven offline with a scripted client."""

from decimal import Decimal as D
from typing import Any

import pytest

from app.agent.options import request_options
from evals import harness
from evals.cases import Case, load_cases, problems
from evals.golden import GoldenClient
from tests.conftest import TEST_DATABASE_URL

REQUIRED_CATEGORIES = {
    "ventas",
    "compras",
    "gastos",
    "merma",
    "conteo",
    "tasa",
    "aportes",
    "movimientos",
    "consultas",
    "cierre",
    "correcciones",
    "falta_info",
    "fuera_de_tema",
    "adversarial",
}


@pytest.fixture(scope="module")
def cases() -> dict[str, Case]:
    return {case.id: case for case in load_cases()}


def test_the_cases_only_name_tools_arguments_and_fixtures_that_exist(
    cases: dict[str, Case],
) -> None:
    assert problems(list(cases.values())) == []
    assert len(cases) >= 40
    assert {case.categoria for case in cases.values()} == REQUIRED_CATEGORIES
    multi_turn = [case for case in cases.values() if len(case.turnos) > 1]
    assert len(multi_turn) >= 10


def test_a_case_naming_an_unknown_tool_or_argument_is_reported(cases: dict[str, Case]) -> None:
    bad = _replace_turn(
        cases["venta_pago_movil"],
        0,
        llamadas=[
            {"herramienta": "registrar_venta", "args": {"cartons": 3}},
            {"herramienta": "vender", "args": {}},
        ],
    )
    assert problems([bad]) == [
        "venta_pago_movil turno 1: registrar_venta no tiene el argumento cartons",
        "venta_pago_movil turno 1: no existe la herramienta vender",
    ]


async def _run(cases: list[Case], clients: dict[str, Any] | None = None) -> list[Any]:
    clients = clients or {}
    return await harness.run_all(
        cases,
        ["claude-haiku-5-5"],
        1,
        lambda case: clients.get(case.id) or GoldenClient(case),
        request_options,
        harness.EvalDatabases(TEST_DATABASE_URL.replace("francisco_test", "francisco_eval_test")),
        concurrency=4,
    )


async def test_every_case_passes_when_the_model_does_what_it_expects(
    cases: dict[str, Case],
) -> None:
    results = await _run(list(cases.values()))
    failed = {r.case_id: r.failures for r in results if not r.passed}
    assert failed == {}
    summary = harness.summarize(results)["claude-haiku-5-5"]
    assert (summary["runs"], summary["pass_rate"]) == (len(cases), 1.0)


def _replace_turn(case: Case, index: int, **changes: Any) -> Case:
    turns = [turn.model_dump() for turn in case.turnos]
    turns[index] = {**turns[index], **changes}
    return Case.model_validate({**case.model_dump(), "turnos": turns})


async def test_the_scorer_catches_each_kind_of_wrong_answer(cases: dict[str, Case]) -> None:
    sale = cases["venta_pago_movil"]
    wrong_quantity = _replace_turn(
        sale,
        0,
        llamadas=[
            {
                "herramienta": "registrar_venta",
                "args": {"cartones": 2, "sueltos": 4, "forma_pago": "pago_movil"},
            }
        ],
    )
    no_mention = _replace_turn(sale, 0, menciona=["listo"])
    asks = cases["venta_sin_forma_de_pago"]
    guesses = _replace_turn(
        asks,
        0,
        llamadas=[
            {"herramienta": "registrar_venta", "args": {"cartones": 3, "forma_pago": "punto"}}
        ],
    )
    close = cases["cierre_hasta_el_boton"]
    no_buttons = _replace_turn(
        close, 0, llamadas=[{"herramienta": "consultar", "args": {"que": "cierres"}}]
    )
    chat = cases["saludo"]
    writes = _replace_turn(
        chat,
        0,
        llamadas=[{"herramienta": "registrar_merma", "args": {"tipo": "rotos", "sueltos": 1}}],
    )
    controls = {
        "venta_pago_movil": wrong_quantity,
        "venta_sin_forma_de_pago": guesses,
        "cierre_hasta_el_boton": no_buttons,
        "saludo": writes,
    }
    results = {
        r.case_id: r.failures
        for r in await _run(
            [sale, asks, close, chat],
            {key: GoldenClient(bad) for key, bad in controls.items()},
        )
    }
    [mention_failure] = [
        r.failures for r in await _run([sale], {sale.id: GoldenClient(no_mention)})
    ]

    assert any(f.startswith("turno 1: faltó registrar_venta") for f in results[sale.id])
    assert any(f.startswith("estado huevos: se esperaba 266, quedó 296") for f in results[sale.id])
    assert "turno 1: llamó registrar_venta, que estaba prohibida en este turno" in results[asks.id]
    assert "turno 1: la respuesta no trae los botones Confirmar/Cancelar" in results[close.id]
    assert any(f.startswith("turno 1: escritura de más: registrar_merma") for f in results[chat.id])
    assert any("mermas_nuevas" in f for f in results[chat.id])
    assert mention_failure == [
        "turno 1: la respuesta no menciona '19,59'",
        "turno 1: la respuesta no menciona '266'",
    ]


def test_matching_rules() -> None:
    assert harness.matches("1,50", "1.50")
    assert harness.matches(["2026-10-12", "2026-10-11"], "2026-10-11")
    assert harness.matches("~transporte", "Transporte (ida a buscar la caja)")
    assert harness.matches({"partes": {"Daniel": "3.81"}}, {"partes": {"Daniel": "3.81", "x": 1}})
    assert not harness.matches(1, True)
    assert not harness.matches("negocio", "Daniel")
    assert harness.normalize("Ñapa  CAMIÓN") == "napa camion"


def test_cost_and_the_report_table() -> None:
    call = harness.ApiCall(
        latency_s=1.0,
        input_tokens=1_000,
        output_tokens=200,
        cache_read_tokens=4_000,
        cache_write_tokens=0,
    )
    expected = (1_000 * 0.10 + 200 * 0.50 + 4_000 * 0.01) / 1_000_000
    assert harness.request_cost("claude-haiku-5-5", call) == pytest.approx(expected)
    assert D(str(harness.request_cost("claude-sonnet-5-5", call))) == D("0.0044")
    run = harness.RunResult(
        case_id="x",
        category="ventas",
        model="claude-haiku-5-5",
        repeat=1,
        passed=True,
        failures=[],
        turns=[],
        api_calls=[call],
        cost_usd=expected,
        state={},
        transcript=[],
    )
    table = harness.report_table(harness.summarize([run]))
    for label in (
        "pasaron",
        "USD por conversación",
        "latencia por turno con modelo p95",
        "  ventas",
    ):
        assert label in table
