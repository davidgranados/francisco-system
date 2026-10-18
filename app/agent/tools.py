"""The agent's tools: flat, strict schemas in Spanish, one dispatcher for all of them.

The models here are the boundary between the language model and the services: field names
and values follow how the partners talk, and each tool turns them into a service input.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_core import to_jsonable_python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent import pending
from app.config import today
from app.domain import rules
from app.domain.errors import DomainError
from app.domain.types import PaymentMethod
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

MONEY = r"^[0-9]+([.,][0-9]{1,2})?$"
OPTIONAL_MONEY = r"^([0-9]+([.,][0-9]{1,2})?)?$"
RATE = r"^[0-9]+([.,][0-9]{1,4})?$"
RESERVE = r"^([0-9]+([.,][0-9]{1,2})?|[0-9]{1,2}([.,][0-9]{1,2})?%)$"
MONEY_HELP = "Número con punto o coma decimal y sin separador de miles, ej. 1,50 o 17176.51"

# Keywords the strict-mode grammar rejects; Pydantic still enforces them on our side.
UNSUPPORTED_BY_STRICT = frozenset(
    {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"}
    | {"minLength", "maxLength", "maxItems", "uniqueItems"}
)
NOT_FLAT = frozenset({"$defs", "$ref", "anyOf", "allOf", "oneOf", "not", "items"})

FormaPago = Literal["efectivo_usd", "efectivo_bs", "pago_movil", "punto", "no_dijo"]
NOT_SAID = "no_dijo"


class ToolKind(StrEnum):
    READ = "read"
    WRITE = "write"
    CONFIRM = "confirm"
    """Runs only after the partner presses Confirmar; the model gets a dry-run preview."""


@dataclass(frozen=True)
class ToolContext:
    """Who the model acts for: resolves "yo" and owns the actions waiting for a button."""

    chat_id: int
    partner_id: int
    speaker: str


Handler = Callable[[AsyncSession, Any, ToolContext], Awaitable[Any]]


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def money(text: str) -> Decimal:
    return Decimal(text.replace(",", "."))


def optional_money(text: str) -> Decimal | None:
    return money(text) if text else None


def payment(value: FormaPago) -> PaymentMethod:
    if value == NOT_SAID:
        raise DomainError(
            "Falta la forma de pago. Pregúntele al socio si fue efectivo en dólares, efectivo "
            "en bolívares, pago móvil o punto, y no registre nada hasta saberlo."
        )
    return PaymentMethod(value)


def payer(value: str, context: ToolContext) -> str | None:
    """The partner who paid from their pocket, or None when the business paid."""
    name = value.strip()
    if name.lower() == NOT_SAID:
        raise DomainError(
            "Falta saber quién pagó: el negocio o un socio de su bolsillo. Pregúntelo y no "
            "registre nada hasta saberlo."
        )
    if name.lower() == "negocio":
        return None
    return context.speaker if name.lower() == "yo" else name


def partner_name(value: str, context: ToolContext) -> str:
    return context.speaker if value.strip().lower() == "yo" else value.strip()


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON schema as one flat object the strict-mode grammar accepts."""
    schema = model.model_json_schema()
    if NOT_FLAT & schema.keys():
        raise ValueError(f"{model.__name__} schema is not flat")
    properties: dict[str, Any] = {}
    for name, spec in schema.get("properties", {}).items():
        if NOT_FLAT & spec.keys() or spec.get("type") in ("object", "array", None):
            raise ValueError(f"{model.__name__}.{name} must be a flat scalar or enum")
        properties[name] = {
            key: value
            for key, value in spec.items()
            if key != "title" and key not in UNSUPPORTED_BY_STRICT
        }
    return {
        "type": "object",
        "properties": properties,
        "required": schema.get("required", []),
        "additionalProperties": False,
    }


def _day(description: str = "Fecha (AAAA-MM-DD); por defecto hoy") -> Any:
    return Field(default_factory=today, description=description)


def _quantity(description: str) -> Any:
    return Field(ge=0, description=description)


# --- Writes ---------------------------------------------------------------------------


class VentaInput(ToolInput):
    cajas: int = _quantity("Cajas completas de 360 huevos")
    cartones: int = _quantity("Cartones de 30 huevos")
    medios: int = _quantity("Medios cartones de 15 huevos")
    sueltos: int = _quantity("Huevos sueltos (unidades)")
    forma_pago: FormaPago = Field(description="no_dijo si el socio no dijo cómo le pagaron")
    cobrado_usd: str = Field(
        default="",
        pattern=OPTIONAL_MONEY,
        description="Solo si cobró un monto distinto a la lista (descuento), en $",
    )
    cobrado_bs: str = Field(
        default="",
        pattern=OPTIONAL_MONEY,
        description="Solo si el cliente pagó un monto exacto en Bs. " + MONEY_HELP,
    )
    cliente: str = Field(default="", max_length=120)
    fecha: date = _day()


async def _record_sale(session: AsyncSession, p: VentaInput, _: ToolContext) -> Any:
    return await sales.record_sale(
        session,
        sales.SaleInput(
            boxes=p.cajas,
            cartons=p.cartones,
            halves=p.medios,
            units=p.sueltos,
            payment_method=payment(p.forma_pago),
            day=p.fecha,
            charged_usd=optional_money(p.cobrado_usd),
            charged_bs=optional_money(p.cobrado_bs),
            customer=p.cliente or None,
        ),
    )


class CompraInput(ToolInput):
    cajas: int = Field(ge=1, description="Cuántas cajas se compraron")
    costo_por_caja_usd: str = Field(pattern=MONEY, description="Costo de cada caja en $")
    forma_pago: FormaPago
    pagado_por: str = Field(
        description="negocio si salió del dinero del negocio, yo si lo pagó quien escribe, el "
        "nombre de otro socio, o no_dijo"
    )
    proveedor: str = Field(default="", max_length=120)
    fecha: date = _day()


async def _record_purchase(session: AsyncSession, p: CompraInput, ctx: ToolContext) -> Any:
    return await purchases.register_purchase(
        session,
        purchases.PurchaseInput(
            box_count=p.cajas,
            cost_per_box_usd=money(p.costo_por_caja_usd),
            payment_method=payment(p.forma_pago),
            paid_by_partner=payer(p.pagado_por, ctx),
            supplier=p.proveedor or None,
            day=p.fecha,
        ),
    )


class GastoInput(ToolInput):
    concepto: str = Field(min_length=1, max_length=200, description="Ej. Transporte, Bolsas")
    moneda: Literal["usd", "bs"] = Field(description="En qué moneda dijo el monto")
    monto: str = Field(pattern=MONEY, description=MONEY_HELP)
    pagado_por: str = Field(
        description="negocio, yo (quien escribe), el nombre de otro socio, o no_dijo"
    )
    fecha: date = _day()


async def _record_expense(session: AsyncSession, p: GastoInput, ctx: ToolContext) -> Any:
    amount = money(p.monto)
    return await expenses.record_expense(
        session,
        expenses.ExpenseInput(
            concept=p.concepto,
            amount_usd=amount if p.moneda == "usd" else None,
            amount_bs=amount if p.moneda == "bs" else None,
            paid_by_partner=payer(p.pagado_por, ctx),
            day=p.fecha,
        ),
    )


class MermaInput(ToolInput):
    tipo: Literal["rotos", "regalados"]
    cartones: int = _quantity("Cartones de 30 huevos")
    medios: int = _quantity("Medios cartones de 15 huevos")
    sueltos: int = _quantity("Huevos sueltos")
    fecha: date = _day()


async def _record_loss(session: AsyncSession, p: MermaInput, _: ToolContext) -> Any:
    eggs = rules.eggs_in(p.cartones, p.medios, p.sueltos)
    if eggs == 0:
        raise DomainError("Indique cuántos huevos se rompieron o se regalaron.")
    return await inventory.record_loss(
        session,
        inventory.LossInput(kind="broken" if p.tipo == "rotos" else "gift", eggs=eggs, day=p.fecha),
    )


class ConteoInput(ToolInput):
    cajas: int = _quantity("Cajas completas sin abrir")
    cartones: int = _quantity("Cartones de 30 huevos")
    medios: int = _quantity("Medios cartones de 15 huevos")
    sueltos: int = _quantity("Huevos sueltos")
    fecha: date = _day()


async def _record_count(session: AsyncSession, p: ConteoInput, _: ToolContext) -> Any:
    counted = rules.eggs_in(p.cartones, p.medios, p.sueltos, p.cajas)
    return await inventory.record_count(
        session, inventory.CountInput(counted_eggs=counted, day=p.fecha)
    )


class AporteInput(ToolInput):
    socio: str = Field(description="yo si es quien escribe, o el nombre del socio")
    monto_usd: str = Field(pattern=MONEY, description="Monto en $. " + MONEY_HELP)
    nota: str = ""
    fecha: date = _day()


async def _record_contribution(session: AsyncSession, p: AporteInput, ctx: ToolContext) -> Any:
    return await contributions.record_contribution(
        session,
        contributions.ContributionInput(
            partner=partner_name(p.socio, ctx),
            amount_usd=money(p.monto_usd),
            note=p.nota or None,
            day=p.fecha,
        ),
    )


class TasaInput(ToolInput):
    tasa: str = Field(pattern=RATE, description="Bs por dólar, ej. 881,25")
    fecha: date = _day()


async def _set_rate(session: AsyncSession, p: TasaInput, _: ToolContext) -> Any:
    return await rates.set_rate(session, rates.SetRateInput(rate=money(p.tasa), day=p.fecha))


class PreciosInput(ToolInput):
    costo_base_usd: str = Field(
        default="",
        pattern=OPTIONAL_MONEY,
        description="Recalcula todos los precios como si la caja costara esto (ej. el costo "
        "de la caja nueva)",
    )
    precio_caja_usd: str = Field(default="", pattern=OPTIONAL_MONEY)
    precio_carton_usd: str = Field(default="", pattern=OPTIONAL_MONEY)
    precio_medio_usd: str = Field(default="", pattern=OPTIONAL_MONEY)
    precio_unidad_usd: str = Field(default="", pattern=OPTIONAL_MONEY)

    @model_validator(mode="after")
    def something_to_change(self) -> Self:
        if not any(
            (
                self.costo_base_usd,
                self.precio_caja_usd,
                self.precio_carton_usd,
                self.precio_medio_usd,
                self.precio_unidad_usd,
            )
        ):
            raise ValueError("indique un costo base o al menos un precio")
        return self


async def _adjust_prices(session: AsyncSession, p: PreciosInput, _: ToolContext) -> Any:
    return await pricing.adjust_prices(
        session,
        pricing.AdjustPricesInput(
            base_cost_usd=optional_money(p.costo_base_usd),
            box_price=optional_money(p.precio_caja_usd),
            carton_price=optional_money(p.precio_carton_usd),
            half_price=optional_money(p.precio_medio_usd),
            unit_price=optional_money(p.precio_unidad_usd),
        ),
    )


class DevolucionInput(ToolInput):
    gasto_id: int = Field(ge=1, description="El id del gasto, de consultar gastos_pendientes")
    fecha: date = _day()


async def _mark_reimbursed(session: AsyncSession, p: DevolucionInput, _: ToolContext) -> Any:
    return await expenses.mark_reimbursed(session, p.gasto_id, expenses.ReimburseInput(day=p.fecha))


class CierreInput(ToolInput):
    reserva: str = Field(
        pattern=RESERVE,
        description="0 si no hay reserva; un monto en $ (ej. 5,00) o un porcentaje (ej. 10%)",
    )
    fecha: date = _day()

    def settlement_input(self) -> settlements.SettlementInput:
        text = self.reserva.strip()
        if text.endswith("%"):
            return settlements.SettlementInput(
                day=self.fecha, reserve_percent=money(text[:-1]) / 100
            )
        amount = money(text)
        return settlements.SettlementInput(day=self.fecha, reserve_usd=amount or None)


async def _settle(session: AsyncSession, p: CierreInput, _: ToolContext) -> Any:
    return await settlements.execute_settlement(session, p.settlement_input())


class AnulacionInput(ToolInput):
    que: Literal["venta", "compra"]
    id: int = Field(ge=1, description="El id de la venta o la compra, de consultar")
    motivo: str = Field(min_length=1, description="Por qué se anula, en pocas palabras")


async def _void(session: AsyncSession, p: AnulacionInput, _: ToolContext) -> Any:
    reason = purchases.VoidInput(reason=p.motivo)
    if p.que == "venta":
        return await sales.void_sale(session, p.id, reason)
    return await purchases.void_purchase(session, p.id, reason)


# --- Reads ----------------------------------------------------------------------------

Consulta = Literal[
    "existencias",
    "precios",
    "cajas",
    "ventas",
    "compras",
    "gastos_pendientes",
    "aportes",
    "socios",
    "cierres",
    "tasa",
    "dinero",
]

QUERIES: dict[str, Callable[[AsyncSession, date], Awaitable[Any]]] = {
    "existencias": lambda s, _: inventory.stock(s),
    "precios": pricing.price_list,
    "cajas": lambda s, _: boxes.list_boxes(s),
    "ventas": sales.list_sales,
    "compras": lambda s, _: purchases.list_purchases(s, 10),
    "gastos_pendientes": lambda s, _: expenses.pending(s),
    "aportes": lambda s, _: contributions.list_contributions(s),
    "socios": lambda s, _: partners.list_partners(s),
    "cierres": lambda s, _: settlements.list_settlements(s),
    "tasa": rates.rate_for,
    "dinero": lambda s, _: reports.cash_flow(s),
}


class ConsultaInput(ToolInput):
    que: Consulta
    fecha: date = _day("Solo para precios, ventas y tasa; por defecto hoy")


async def _query(session: AsyncSession, p: ConsultaInput, _: ToolContext) -> Any:
    return await QUERIES[p.que](session, p.fecha)


class CajaInput(ToolInput):
    numero: int = Field(ge=1, description="Número de la caja (Caja 1, Caja 2...)")
    que: Literal["hoja", "ganancia"]


async def _box(session: AsyncSession, p: CajaInput, _: ToolContext) -> Any:
    if p.que == "hoja":
        return await boxes.box_sheet(session, p.numero)
    return await boxes.box_profit(session, p.numero)


class ResumenInput(ToolInput):
    desde: date
    hasta: date
    que: Literal["ventas_y_dinero", "existencias_por_dia"]


async def _summary(session: AsyncSession, p: ResumenInput, _: ToolContext) -> Any:
    if p.que == "existencias_por_dia":
        return await inventory.stock_ledger(session, p.desde, p.hasta)
    return await reports.summary(session, reports.PeriodInput(date_from=p.desde, date_to=p.hasta))


# --- Registry -------------------------------------------------------------------------


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[ToolInput]
    handler: Handler
    kind: ToolKind
    examples: tuple[dict[str, Any], ...] = ()

    def definition(self) -> dict[str, Any]:
        definition: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "input_schema": strict_schema(self.input_model),
            "strict": True,
        }
        if self.examples:
            definition["input_examples"] = list(self.examples)
        return definition


TOOLS: list[Tool] = [
    Tool(
        "registrar_venta",
        "Registra una venta de huevos. Úsala cuando el socio dice que vendió algo y ya se sabe "
        "cuánto y cómo le pagaron. Cada presentación va en su campo: cajas (360), cartones (30), "
        "medios cartones (15) y huevos sueltos; los que no se vendieron van en 0. El código "
        "calcula el monto con los precios de la caja abierta y descuenta de la caja más vieja. "
        "Si no dijo la forma de pago, pregúntala antes; si igual la llamas, usa no_dijo. No la "
        "uses para huevos rotos o regalados (registrar_merma).",
        VentaInput,
        _record_sale,
        ToolKind.WRITE,
        (
            {"cajas": 0, "cartones": 3, "medios": 0, "sueltos": 4, "forma_pago": "pago_movil"},
            {"cajas": 1, "cartones": 0, "medios": 0, "sueltos": 0, "forma_pago": "efectivo_usd"},
            {
                "cajas": 0,
                "cartones": 4,
                "medios": 0,
                "sueltos": 0,
                "forma_pago": "efectivo_bs",
                "cobrado_bs": "21947,50",
            },
        ),
    ),
    Tool(
        "registrar_compra",
        "Registra la compra de cajas de huevos y crea las cajas numeradas con sus precios. "
        "Úsala cuando el socio dice que compró cajas y a cuánto cada una. Si la respuesta trae "
        "price_notice, la caja nueva es más cara que la que se vende: díselo y ofrece subir los "
        "precios con ajustar_precios. No la uses para gastos que no son huevos.",
        CompraInput,
        _record_purchase,
        ToolKind.WRITE,
        (
            {
                "cajas": 1,
                "costo_por_caja_usd": "63",
                "forma_pago": "efectivo_usd",
                "pagado_por": "negocio",
            },
        ),
    ),
    Tool(
        "registrar_gasto",
        "Registra un gasto que no son huevos: transporte, bolsas, cartones vacíos, comisiones. "
        "Pon el monto en la moneda en que lo dijo el socio; el código convierte con la tasa. Si "
        "dice que lo pagó él ('pagué yo', 'lo puse yo'), pagado_por es yo y queda pendiente de "
        "devolverle. No la uses para compras de cajas ni para aportes.",
        GastoInput,
        _record_expense,
        ToolKind.WRITE,
        (
            {"concepto": "Transporte", "moneda": "usd", "monto": "1,50", "pagado_por": "yo"},
            {"concepto": "Bolsas", "moneda": "bs", "monto": "350", "pagado_por": "negocio"},
        ),
    ),
    Tool(
        "registrar_merma",
        "Registra huevos que salen sin venderse: rotos ('se partieron', 'se rompieron') o "
        "regalados. Salen de la caja abierta y no se cobran. Pon la cantidad en cartones, "
        "medios o sueltos; lo demás en 0. No la uses para ventas ni para un conteo físico.",
        MermaInput,
        _record_loss,
        ToolKind.WRITE,
        ({"tipo": "rotos", "cartones": 0, "medios": 0, "sueltos": 2},),
    ),
    Tool(
        "registrar_conteo",
        "Registra un conteo físico de lo que hay en el depósito. Si faltan huevos, la "
        "diferencia queda como merma; si sobran, solo se avisa. Úsala cuando el socio dice que "
        "contó. No la uses para preguntar cuántos quedan (eso es consultar existencias).",
        ConteoInput,
        _record_count,
        ToolKind.WRITE,
        ({"cajas": 0, "cartones": 8, "medios": 0, "sueltos": 6},),
    ),
    Tool(
        "registrar_aporte",
        "Registra dinero que un socio mete al negocio (un aporte). No es ganancia ni venta. "
        "Úsala solo cuando el socio dice que puso o aportó dinero para el negocio, no cuando "
        "pagó un gasto de su bolsillo (eso es registrar_gasto con pagado_por).",
        AporteInput,
        _record_contribution,
        ToolKind.WRITE,
        ({"socio": "yo", "monto_usd": "100"},),
    ),
    Tool(
        "fijar_tasa",
        "Guarda a mano la tasa BCV (Bs por dólar) de un día, cuando el socio la dice o la "
        "corrige. La del día ya viene en el contexto; no la uses para consultarla.",
        TasaInput,
        _set_rate,
        ToolKind.WRITE,
        ({"tasa": "881,25"},),
    ),
    Tool(
        "ajustar_precios",
        "Cambia los precios de la caja que se está vendiendo. Con costo_base_usd recalcula "
        "todos los precios como si la caja costara eso (lo normal tras comprar una caja más "
        "cara). Con precio_* fija a mano solo los precios que el socio dijo. Úsala solo si el "
        "socio lo pide o acepta tu oferta.",
        PreciosInput,
        _adjust_prices,
        ToolKind.WRITE,
        ({"costo_base_usd": "63"}, {"precio_carton_usd": "6,50"}),
    ),
    Tool(
        "marcar_gasto_devuelto",
        "Marca como devuelto a un socio un gasto que pagó de su bolsillo, cuando se lo "
        "devolvieron antes del cierre. El cierre ya los devuelve solo; no hace falta después.",
        DevolucionInput,
        _mark_reimbursed,
        ToolKind.WRITE,
    ),
    Tool(
        "preparar_cierre",
        "Prepara el cierre y el reparto: cajas terminadas con su caja siguiente comprada, "
        "gastos pendientes, reserva, ganancia neta, parte de cada socio y devoluciones. No "
        "guarda nada: devuelve la vista previa y el bot le pone al mensaje los botones "
        "Confirmar y Cancelar. Úsala cuando el socio pide el cierre, la repartición o 'cuánto "
        "nos toca'. Muestra el reparto y dile que toque Confirmar; un 'sí' escrito no confirma.",
        CierreInput,
        _settle,
        ToolKind.CONFIRM,
        ({"reserva": "0"}, {"reserva": "10%"}, {"reserva": "5,00"}),
    ),
    Tool(
        "preparar_anulacion",
        "Prepara la anulación de una venta o una compra registrada por error; la venta anulada "
        "devuelve sus huevos al inventario. No anula nada todavía: el bot muestra los botones "
        "Confirmar y Cancelar. Busca antes el id con consultar (ventas o compras). Para "
        "corregir una cantidad, prepara la anulación y registra la venta correcta cuando el "
        "socio confirme.",
        AnulacionInput,
        _void,
        ToolKind.CONFIRM,
        ({"que": "venta", "id": 12, "motivo": "eran 4 cartones, no 3"},),
    ),
    Tool(
        "consultar",
        "Lee datos sin cambiar nada. que: existencias (huevos y cajas que quedan, costo "
        "promedio), precios (lista del día en $ y Bs), cajas (estado de cada caja), ventas (las "
        "de un día, con su id), compras (las últimas, con su id), gastos_pendientes (sin cierre "
        "o por devolver a un socio, con su id), aportes, socios, cierres, tasa (BCV de un día), "
        "dinero (lo que entró y salió del negocio desde el principio).",
        ConsultaInput,
        _query,
        ToolKind.READ,
    ),
    Tool(
        "ver_caja",
        "Muestra una caja por su número. que: hoja (ventas y rotos día por día) o ganancia "
        "(solo existe cuando la caja se acabó y ya se compró la siguiente).",
        CajaInput,
        _box,
        ToolKind.READ,
    ),
    Tool(
        "resumen",
        "Resumen entre dos fechas. que: ventas_y_dinero (ventas, compras, gastos, mermas y "
        "dinero por forma de pago) o existencias_por_dia (entradas, salidas y lo que queda cada "
        "día). Para 'la semana' usa del lunes a hoy.",
        ResumenInput,
        _summary,
        ToolKind.READ,
    ),
]

REGISTRY: dict[str, Tool] = {tool.name: tool for tool in TOOLS}


def tool_definitions() -> list[dict[str, Any]]:
    definitions = [tool.definition() for tool in TOOLS]
    definitions[-1]["cache_control"] = {"type": "ephemeral"}
    return definitions


@dataclass(frozen=True)
class ToolOutcome:
    content: str
    is_error: bool
    pending_id: int | None = None


PENDING_NOTICE = (
    "No se guardó nada todavía. Muéstrale al socio lo que va a pasar; el bot pone los botones "
    "Confirmar y Cancelar debajo de tu mensaje y solo con Confirmar se hace."
)


def _validation_message(error: ValidationError) -> str:
    problems = "; ".join(
        f"{'.'.join(str(part) for part in issue['loc']) or 'datos'}: {issue['msg']}"
        for issue in error.errors()
    )
    return f"Datos inválidos: {problems}"


def _json(value: Any) -> Any:
    return to_jsonable_python(value)


def _same_effect(preview: Any, result: Any) -> bool:
    """A new settlement gets a new id on each run; everything else must match the preview."""
    if isinstance(preview, dict) and isinstance(result, dict):
        return {k: v for k, v in preview.items() if k != "id"} == {
            k: v for k, v in result.items() if k != "id"
        }
    return bool(preview == result)


def find_tool(name: str) -> Tool | None:
    """Exact name first, then one that differs only in letter case."""
    return REGISTRY.get(name) or next(
        (tool for tool in TOOLS if tool.name.lower() == name.lower()), None
    )


async def _dry_run(
    tool: Tool,
    params: ToolInput,
    session_factory: async_sessionmaker[AsyncSession],
    context: ToolContext,
) -> ToolOutcome:
    """Run the action and roll it back, so the preview is exactly what Confirmar will do."""
    async with session_factory() as session:
        transaction = await session.begin()
        try:
            preview = _json(await tool.handler(session, params, context))
        finally:
            await transaction.rollback()
    async with session_factory() as session, session.begin():
        pending_id = await pending.create(
            session,
            chat_id=context.chat_id,
            partner_id=context.partner_id,
            tool=tool.name,
            arguments=params.model_dump(mode="json"),
            preview=preview,
        )
    content = {"vista_previa": preview, "aviso": PENDING_NOTICE}
    return ToolOutcome(json.dumps(content, ensure_ascii=False), False, pending_id)


async def dispatch(
    name: str,
    raw_input: Any,
    session_factory: async_sessionmaker[AsyncSession],
    context: ToolContext,
) -> ToolOutcome:
    """Validate the model's input, run the tool in its own transaction, report the result."""
    tool = find_tool(name)
    if tool is None:
        known = ", ".join(REGISTRY)
        return ToolOutcome(f"No existe la herramienta {name}. Las que hay: {known}.", True)
    try:
        params = tool.input_model.model_validate(raw_input)
        if tool.kind == ToolKind.CONFIRM:
            return await _dry_run(tool, params, session_factory, context)
        async with session_factory() as session, session.begin():
            result = await tool.handler(session, params, context)
    except ValidationError as error:
        return ToolOutcome(_validation_message(error), is_error=True)
    except DomainError as error:
        return ToolOutcome(error.message, is_error=True)
    except Exception:
        logger.exception("tool %s failed", tool.name)
        return ToolOutcome("Error interno al ejecutar la herramienta.", is_error=True)
    return ToolOutcome(json.dumps(_json(result), ensure_ascii=False), is_error=False)


@dataclass(frozen=True)
class Resolution:
    """What pressing a button did; `outcome` is None when the press was refused."""

    message: str
    outcome: pending.Outcome | None = None
    tool: str | None = None
    result: Any = None
    final: bool = True


CANCELLED = "Cancelado. No se guardó nada."
CHANGED = (
    "No lo hice: algo cambió desde la vista previa (una venta, un gasto o una caja nueva). "
    "Pídalo de nuevo para ver los números actualizados."
)


class _Changed(Exception):
    pass


async def resolve_pending(
    session_factory: async_sessionmaker[AsyncSession],
    action_id: int,
    context: ToolContext,
    *,
    confirm: bool,
) -> Resolution:
    """Confirm or cancel a prepared action, once, for the partner who prepared it."""
    async with session_factory() as session, session.begin():
        action = await pending.claim(session, action_id, context.chat_id, context.partner_id)
        if isinstance(action, pending.Refusal):
            return Resolution(action.message, final=action.final)
        if not confirm:
            action.outcome = pending.Outcome.CANCELLED
            return Resolution(CANCELLED, action.outcome, action.tool)
        tool = REGISTRY[action.tool]
        try:
            async with session.begin_nested():
                params = tool.input_model.model_validate(action.arguments)
                result = _json(await tool.handler(session, params, context))
                if not _same_effect(action.preview, result):
                    raise _Changed
        except _Changed:
            action.outcome = pending.Outcome.CHANGED
            return Resolution(CHANGED, action.outcome, action.tool)
        except DomainError as error:
            action.outcome = pending.Outcome.FAILED
            return Resolution(error.message, action.outcome, action.tool)
        action.outcome = pending.Outcome.CONFIRMED
        return Resolution("Hecho.", action.outcome, action.tool, result)
