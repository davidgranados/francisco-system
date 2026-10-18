"""The tool surface the model sees, and what the dispatcher does with each kind of input."""

import json
import re
from decimal import Decimal as D
from typing import Any

import pytest

from app.agent import tools
from app.agent.tools import ToolContext, dispatch
from app.config import today
from app.db import SessionLocal
from app.domain.types import PaymentMethod
from app.services import expenses, purchases, rates, sales
from tests.conftest import Call

# Limits of strict tool use, per request: docs/investigacion-haiku.md, section 5.
MAX_STRICT_TOOLS = 20
MAX_OPTIONAL_PARAMETERS = 24
MAX_UNION_PARAMETERS = 16
STRICT_SCALAR_KEYS = {"type", "description", "enum", "const", "default", "format", "pattern"}
STRICT_FORMATS = {"date", "date-time", "time", "duration", "email", "hostname", "uri", "uuid"}
SPEAKER = ToolContext(speaker="Socio A")


def _schemas() -> list[tuple[str, dict[str, Any]]]:
    return [(d["name"], d["input_schema"]) for d in tools.tool_definitions()]


def test_every_tool_is_strict_with_a_flat_object_schema() -> None:
    for definition in tools.tool_definitions():
        assert definition["strict"] is True, definition["name"]
        assert re.fullmatch(r"[a-z_]{1,64}", definition["name"])
        schema = definition["input_schema"]
        assert set(schema) == {"type", "properties", "required", "additionalProperties"}
        assert (schema["type"], schema["additionalProperties"]) == ("object", False)
        assert set(schema["required"]) <= set(schema["properties"])
        for name, spec in schema["properties"].items():
            where = f"{definition['name']}.{name}"
            assert set(spec) <= STRICT_SCALAR_KEYS, where
            assert spec["type"] in {"string", "integer", "boolean"}, where
            assert spec.get("format", "date") in STRICT_FORMATS, where
            if "pattern" in spec:
                assert not re.search(r"\\[1-9bB]|\(\?[=!<]", spec["pattern"]), where


def test_the_tool_set_fits_the_strict_mode_limits() -> None:
    schemas = _schemas()
    optional = sum(len(s["properties"]) - len(s["required"]) for _, s in schemas)
    unions = sum(
        isinstance(spec["type"], list) for _, s in schemas for spec in s["properties"].values()
    )
    assert len(schemas) <= MAX_STRICT_TOOLS
    assert optional <= MAX_OPTIONAL_PARAMETERS
    assert unions <= MAX_UNION_PARAMETERS
    assert len(json.dumps(tools.tool_definitions())) < 40_000


def test_input_examples_validate_against_their_tool() -> None:
    for tool in tools.TOOLS:
        properties = tool.definition()["input_schema"]["properties"]
        for example in tool.examples:
            assert set(example) <= set(properties), tool.name
            tool.input_model.model_validate(example)


def test_the_last_tool_carries_the_cache_breakpoint() -> None:
    definitions = tools.tool_definitions()
    assert definitions[-1]["cache_control"] == {"type": "ephemeral"}
    assert all("cache_control" not in d for d in definitions[:-1])


def test_a_nested_or_nullable_field_is_refused_by_the_schema_builder() -> None:
    class Nullable(tools.ToolInput):
        note: str | None = None

    with pytest.raises(ValueError, match="flat"):
        tools.strict_schema(Nullable)


@pytest.fixture
async def stocked(call: Call) -> None:
    await call(rates.set_rate, rates.SetRateInput(day=today(), rate=D("880.00")))
    await call(
        purchases.register_purchase,
        purchases.PurchaseInput(
            box_count=1, cost_per_box_usd=D("60.00"), payment_method=PaymentMethod.CASH_USD
        ),
    )


async def _run(name: str, arguments: dict[str, Any]) -> tools.ToolOutcome:
    return await dispatch(name, arguments, SessionLocal, SPEAKER)


SALE = {"cajas": 0, "cartones": 3, "medios": 0, "sueltos": 4}


@pytest.mark.usefixtures("stocked")
async def test_a_sale_without_payment_method_is_refused_and_writes_nothing(call: Call) -> None:
    outcome = await _run("registrar_venta", {**SALE, "forma_pago": "no_dijo"})
    assert outcome.is_error
    assert "Falta la forma de pago" in outcome.content
    assert await call(sales.list_sales) == []


@pytest.mark.usefixtures("stocked")
async def test_a_sale_charged_in_bolivares_takes_a_comma_decimal(call: Call) -> None:
    outcome = await _run(
        "registrar_venta", {**SALE, "forma_pago": "efectivo_bs", "cobrado_bs": "17176,51"}
    )
    assert not outcome.is_error, outcome.content
    [sale] = await call(sales.list_sales)
    assert (sale.amount_bs, sale.amount_usd, sale.eggs) == (D("17176.51"), D("19.52"), 94)


@pytest.mark.usefixtures("two_partners", "stocked")
async def test_yo_pays_as_the_partner_who_writes(call: Call) -> None:
    outcome = await _run(
        "registrar_gasto",
        {"concepto": "Transporte", "moneda": "usd", "monto": "1,50", "pagado_por": "yo"},
    )
    assert not outcome.is_error, outcome.content
    [expense] = await call(expenses.pending)
    assert (expense.paid_by_partner, expense.amount_usd) == ("Socio A", D("1.50"))


@pytest.mark.usefixtures("two_partners", "stocked")
async def test_an_unknown_payer_writes_nothing(call: Call) -> None:
    gasto = {"concepto": "Bolsas", "moneda": "usd", "monto": "0.40"}
    for payer, message in (("no_dijo", "Falta saber quién pagó"), ("Pedro", "No conozco")):
        outcome = await _run("registrar_gasto", {**gasto, "pagado_por": payer})
        assert outcome.is_error
        assert message in outcome.content
    assert await call(expenses.pending) == []


@pytest.mark.usefixtures("stocked")
async def test_broken_eggs_in_cartons_are_counted_in_eggs() -> None:
    outcome = await _run(
        "registrar_merma", {"tipo": "rotos", "cartones": 1, "medios": 0, "sueltos": 2}
    )
    assert json.loads(outcome.content)["eggs"] == 32


@pytest.mark.usefixtures("stocked")
async def test_a_tool_name_in_the_wrong_case_still_runs() -> None:
    outcome = await _run("Consultar", {"que": "existencias"})
    assert json.loads(outcome.content)["total_eggs"] == 360
    unknown = await _run("borrar_todo", {})
    assert unknown.is_error
    assert "registrar_venta" in unknown.content
