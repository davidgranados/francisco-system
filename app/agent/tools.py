"""The agent's tool registry: one table row per tool, one dispatcher for all of them."""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_core import to_jsonable_python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import today
from app.domain.errors import DomainError
from app.services import (
    boxes,
    contributions,
    expenses,
    inventory,
    partners,
    pricing,
    purchases,
    rates,
    reports,
    sales,
    settlements,
)

logger = logging.getLogger(__name__)

Handler = Callable[[AsyncSession, Any], Awaitable[Any]]

CONFIRMATION_REQUIRED = (
    "Falta confirmación. Muestre al usuario lo que se va a hacer (para un cierre, la vista "
    "previa), pregúntele si confirma y, solo si dice que sí, vuelva a llamar con confirmado=true."
)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Handler
    requires_confirmation: bool = False

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(by_alias=True),
        }


@dataclass(frozen=True)
class ToolOutcome:
    content: str
    is_error: bool


class Confirmation(BaseModel):
    model_config = ConfigDict(validate_by_name=True, validate_by_alias=True)

    confirmed: bool = Field(
        default=False,
        alias="confirmado",
        description="true solo después de que el usuario confirmó explícitamente",
    )


class NoInput(BaseModel):
    pass


class DayInput(BaseModel):
    day: date | None = Field(default=None, description="Fecha; por defecto hoy")


class BoxNumberInput(BaseModel):
    number: int = Field(ge=1, description="Número de la caja")


class LedgerInput(BaseModel):
    date_from: date
    date_to: date


class CashInput(BaseModel):
    date_from: date | None = None
    date_to: date | None = None


class VoidSaleInput(purchases.VoidInput, Confirmation):
    sale_id: int


class VoidPurchaseInput(purchases.VoidInput, Confirmation):
    purchase_id: int


class ExecuteSettlementInput(settlements.SettlementInput, Confirmation):
    pass


class ReimburseExpenseInput(expenses.ReimburseInput):
    expense_id: int


TOOLS: list[Tool] = [
    Tool(
        "consultar_tasa",
        "Tasa BCV (Bs por dólar) de un día. Si no hay de hoy la busca en el BCV.",
        DayInput,
        lambda s, p: rates.rate_for(s, p.day or today()),
    ),
    Tool("fijar_tasa", "Guarda a mano la tasa BCV de un día.", rates.SetRateInput, rates.set_rate),
    Tool(
        "registrar_compra",
        "Registra la compra de cajas. Crea las cajas numeradas con sus precios.",
        purchases.PurchaseInput,
        purchases.register_purchase,
    ),
    Tool(
        "listar_compras",
        "Últimas compras con sus cajas.",
        NoInput,
        lambda s, _: purchases.list_purchases(s, 10),
    ),
    Tool(
        "anular_compra",
        "Anula una compra cuyas cajas no se han tocado. Pide confirmación antes.",
        VoidPurchaseInput,
        lambda s, p: purchases.void_purchase(s, p.purchase_id, p),
        requires_confirmation=True,
    ),
    Tool(
        "registrar_venta",
        "Registra una venta en cartones, medios y huevos sueltos. Se cobra con los precios de "
        "la caja abierta y se descuenta de la caja más vieja.",
        sales.SaleInput,
        sales.record_sale,
    ),
    Tool(
        "listar_ventas",
        "Ventas de un día, con su id.",
        DayInput,
        lambda s, p: sales.list_sales(s, p.day),
    ),
    Tool(
        "anular_venta",
        "Anula una venta y devuelve sus huevos al inventario. Pide confirmación antes.",
        VoidSaleInput,
        lambda s, p: sales.void_sale(s, p.sale_id, p),
        requires_confirmation=True,
    ),
    Tool(
        "registrar_rotos_o_regalados",
        "Huevos rotos (no se cobran) o regalados. Salen de la caja abierta.",
        inventory.LossInput,
        inventory.record_loss,
    ),
    Tool(
        "registrar_conteo",
        "Conteo físico de huevos. Si faltan, la diferencia queda como merma.",
        inventory.CountInput,
        inventory.record_count,
    ),
    Tool(
        "ver_existencias",
        "Huevos y cajas que quedan, por caja, con el costo promedio.",
        NoInput,
        lambda s, _: inventory.stock(s),
    ),
    Tool(
        "control_de_existencias",
        "Plantilla D: entradas, vendidos, rotos y lo que queda, día por día.",
        LedgerInput,
        lambda s, p: inventory.stock_ledger(s, p.date_from, p.date_to),
    ),
    Tool(
        "registrar_gasto",
        "Gasto que no son huevos (transporte, bolsas...). Si lo pagó un socio queda por devolver.",
        expenses.ExpenseInput,
        expenses.record_expense,
    ),
    Tool(
        "marcar_gasto_devuelto",
        "Marca como devuelto al socio un gasto que pagó de su bolsillo.",
        ReimburseExpenseInput,
        lambda s, p: expenses.mark_reimbursed(s, p.expense_id, p),
    ),
    Tool(
        "gastos_pendientes",
        "Gastos que aún no entran en un cierre o que falta devolver a un socio.",
        NoInput,
        lambda s, _: expenses.pending(s),
    ),
    Tool(
        "lista_de_precios",
        "Plantilla A: precios del día en $ y Bs de la caja que se está vendiendo.",
        DayInput,
        lambda s, p: pricing.price_list(s, p.day),
    ),
    Tool(
        "ajustar_precios",
        "Cambia los precios de una caja: desde un costo base (ej. el de la caja nueva) o a mano.",
        pricing.AdjustPricesInput,
        pricing.adjust_prices,
    ),
    Tool(
        "ver_cajas",
        "Cajas no cerradas con su estado y huevos.",
        NoInput,
        lambda s, _: boxes.list_boxes(s),
    ),
    Tool(
        "hoja_de_caja",
        "Plantilla C: ventas y rotos de una caja, día por día.",
        BoxNumberInput,
        lambda s, p: boxes.box_sheet(s, p.number),
    ),
    Tool(
        "ganancia_de_caja",
        "Plantilla G: ganancia de una caja terminada con la siguiente ya comprada.",
        BoxNumberInput,
        lambda s, p: boxes.box_profit(s, p.number),
    ),
    Tool(
        "vista_previa_cierre",
        "Plantilla H sin guardar nada: cajas cerradas, gastos, reserva, ganancia neta y reparto.",
        settlements.SettlementInput,
        settlements.preview_settlement,
    ),
    Tool(
        "ejecutar_cierre",
        "Guarda el cierre y el reparto. Antes muestre la vista previa y pida confirmación.",
        ExecuteSettlementInput,
        settlements.execute_settlement,
        requires_confirmation=True,
    ),
    Tool(
        "ver_cierres",
        "Últimos cierres guardados.",
        NoInput,
        lambda s, _: settlements.list_settlements(s),
    ),
    Tool(
        "registrar_aporte",
        "Dinero que un socio pone en el negocio. No es ganancia.",
        contributions.ContributionInput,
        contributions.record_contribution,
    ),
    Tool(
        "ver_aportes",
        "Aportes de los socios.",
        NoInput,
        lambda s, _: contributions.list_contributions(s),
    ),
    Tool(
        "resumen_periodo",
        "Ventas, compras, gastos, mermas y dinero entre dos fechas.",
        reports.PeriodInput,
        reports.summary,
    ),
    Tool(
        "dinero_del_negocio",
        "Cuánto dinero entró y salió del negocio (sin fechas: desde el principio).",
        CashInput,
        lambda s, p: reports.cash_flow(s, p.date_from, p.date_to),
    ),
    Tool("ver_socios", "Socios y su porcentaje.", NoInput, lambda s, _: partners.list_partners(s)),
]

REGISTRY: dict[str, Tool] = {tool.name: tool for tool in TOOLS}


def tool_definitions() -> list[dict[str, Any]]:
    definitions = [tool.definition() for tool in TOOLS]
    definitions[-1]["cache_control"] = {"type": "ephemeral"}
    return definitions


def _validation_message(error: ValidationError) -> str:
    problems = "; ".join(
        f"{'.'.join(str(part) for part in issue['loc']) or 'datos'}: {issue['msg']}"
        for issue in error.errors()
    )
    return f"Datos inválidos: {problems}"


async def dispatch(
    name: str, raw_input: Any, session_factory: async_sessionmaker[AsyncSession]
) -> ToolOutcome:
    """Validate the model's input, run the service in its own transaction, report the result."""
    tool = REGISTRY.get(name)
    if tool is None:
        return ToolOutcome(f"No existe la herramienta {name}.", is_error=True)
    try:
        params = tool.input_model.model_validate(raw_input)
    except ValidationError as error:
        return ToolOutcome(_validation_message(error), is_error=True)
    if tool.requires_confirmation and not (isinstance(params, Confirmation) and params.confirmed):
        return ToolOutcome(CONFIRMATION_REQUIRED, is_error=True)
    try:
        async with session_factory() as session, session.begin():
            result = await tool.handler(session, params)
    except DomainError as error:
        return ToolOutcome(error.message, is_error=True)
    except Exception:
        logger.exception("tool %s failed", name)
        return ToolOutcome("Error interno al ejecutar la herramienta.", is_error=True)
    return ToolOutcome(json.dumps(to_jsonable_python(result), ensure_ascii=False), is_error=False)
