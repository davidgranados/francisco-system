"""Named starting states for the eval cases, built through the services.

Each fixture fixes its own "today" so the cases can name dates. The partners are Francisco
(60 %, Telegram 111) and Daniel (40 %, Telegram 222). The week is the one of cuaderno Part 9.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.types import PaymentMethod
from app.services import expenses, inventory, partners, purchases, rates, sales

PARTNERS = {"Francisco": 111, "Daniel": 222}
SHARES = {"Francisco": D("0.60"), "Daniel": D("0.40")}

RATES = {
    date(2026, 10, 11): D("876.20"),
    date(2026, 10, 12): D("876.80"),
    date(2026, 10, 13): D("877.30"),
    date(2026, 10, 14): D("877.90"),
    date(2026, 10, 15): D("878.40"),
    date(2026, 10, 16): D("879.00"),
    date(2026, 10, 17): D("879.50"),
    date(2026, 10, 18): D("880.00"),
}

MONDAY, TUESDAY, WEDNESDAY = date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14)
THURSDAY, FRIDAY, SUNDAY = date(2026, 10, 15), date(2026, 10, 16), date(2026, 10, 18)

Factory = async_sessionmaker[AsyncSession]


async def _call(factory: Factory, service: Callable[..., Awaitable[Any]], *args: Any) -> Any:
    async with factory() as session, session.begin():
        return await service(session, *args)


async def _partners_and_rates(factory: Factory, until: date) -> None:
    await _call(
        factory,
        partners.replace_partners,
        [
            partners.PartnerEntry(name=name, share=SHARES[name], telegram_user_id=telegram)
            for name, telegram in PARTNERS.items()
        ],
    )
    for day, rate in RATES.items():
        if day <= until:
            await _call(factory, rates.set_rate, rates.SetRateInput(day=day, rate=rate))


async def _buy(
    factory: Factory, day: date, cost: str, paid_by: str | None = None, count: int = 1
) -> None:
    await _call(
        factory,
        purchases.register_purchase,
        purchases.PurchaseInput(
            day=day,
            box_count=count,
            cost_per_box_usd=D(cost),
            payment_method=PaymentMethod.CASH_USD,
            supplier="Granja X",
            paid_by_partner=paid_by,
        ),
    )


async def _sell(
    factory: Factory, day: date, cartons: int, halves: int, units: int, method: PaymentMethod
) -> None:
    await _call(
        factory,
        sales.record_sale,
        sales.SaleInput(
            day=day, cartons=cartons, halves=halves, units=units, payment_method=method
        ),
    )


async def _expense(factory: Factory, day: date, concept: str, usd: str, paid_by: str | None):
    await _call(
        factory,
        expenses.record_expense,
        expenses.ExpenseInput(day=day, concept=concept, amount_usd=D(usd), paid_by_partner=paid_by),
    )


async def _week_until(factory: Factory, today: date) -> None:
    """Part 9 up to the start of `today`: everything dated earlier, plus Monday's bags."""
    await _partners_and_rates(factory, today)
    await _buy(factory, date(2026, 10, 11), "60.00")
    await _expense(factory, MONDAY, "Bolsas plásticas", "0.40", None)
    if today > MONDAY:
        await _sell(factory, MONDAY, 3, 0, 4, PaymentMethod.MOBILE_PAYMENT)
    if today > TUESDAY:
        await _sell(factory, TUESDAY, 2, 1, 2, PaymentMethod.CASH_USD)
    if today > WEDNESDAY:
        await _sell(factory, WEDNESDAY, 3, 0, 3, PaymentMethod.CARD)
        await _call(
            factory,
            inventory.record_loss,
            inventory.LossInput(day=WEDNESDAY, kind="broken", eggs=3),
        )
    if today > THURSDAY:
        await _buy(factory, THURSDAY, "63.00")
        await _expense(factory, THURSDAY, "Transporte (ida a buscar la caja)", "1.50", "Francisco")
        await _sell(factory, THURSDAY, 2, 0, 3, PaymentMethod.MOBILE_PAYMENT)
    if today > FRIDAY:
        await _sell(factory, FRIDAY, 1, 0, 0, PaymentMethod.CASH_BS)


async def sin_huevos(factory: Factory) -> None:
    await _partners_and_rates(factory, MONDAY)


async def semana_parte9_lunes(factory: Factory) -> None:
    """Caja 1 (costo 60) llena, bolsas de 0,40 anotadas. 360 huevos."""
    await _week_until(factory, MONDAY)


async def semana_parte9_miercoles(factory: Factory) -> None:
    """Ventas del lunes y el martes hechas. Quedan 189 huevos."""
    await _week_until(factory, WEDNESDAY)


async def semana_parte9_jueves(factory: Factory) -> None:
    """Hasta el miércoles con sus 3 rotos. Quedan 93 huevos de la Caja 1."""
    await _week_until(factory, THURSDAY)


async def semana_parte9_domingo(factory: Factory) -> None:
    """Semana completa: Caja 1 terminada, Caja 2 (costo 63) llena, transporte por devolver."""
    await _week_until(factory, SUNDAY)


async def venta_reciente(factory: Factory) -> None:
    """Lunes con una venta de 3 cartones por pago móvil (venta 1) recién anotada."""
    await _week_until(factory, MONDAY)
    await _sell(factory, MONDAY, 3, 0, 0, PaymentMethod.MOBILE_PAYMENT)


async def compra_repetida(factory: Factory) -> None:
    """Lunes: la compra de una caja a 60 de hoy quedó anotada dos veces (compras 2 y 3)."""
    await _week_until(factory, MONDAY)
    await _buy(factory, MONDAY, "60.00")
    await _buy(factory, MONDAY, "60.00")


@dataclass(frozen=True)
class Fixture:
    today: date
    build: Callable[[Factory], Awaitable[None]]


FIXTURES: dict[str, Fixture] = {
    "sin_huevos": Fixture(MONDAY, sin_huevos),
    "semana_parte9_lunes": Fixture(MONDAY, semana_parte9_lunes),
    "semana_parte9_miercoles": Fixture(WEDNESDAY, semana_parte9_miercoles),
    "semana_parte9_jueves": Fixture(THURSDAY, semana_parte9_jueves),
    "semana_parte9_domingo": Fixture(SUNDAY, semana_parte9_domingo),
    "venta_reciente": Fixture(MONDAY, venta_reciente),
    "compra_repetida": Fixture(MONDAY, compra_repetida),
}
