from collections import defaultdict
from datetime import date
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain import rules
from app.domain.errors import DomainError
from app.domain.types import BoxStatus, MovementKind, PaymentMethod
from app.models import Box, EggMovement, Sale
from app.services.ledger import used_eggs
from app.services.pages import Page, PageRequest, fetch_page


class BoxView(BaseModel):
    number: int
    status: BoxStatus
    purchase_day: date
    cost_usd: Decimal
    box_price: Decimal
    carton_price: Decimal
    half_price: Decimal
    unit_price: Decimal
    remaining_eggs: int
    opened_on: date | None
    finished_on: date | None


class BoxProfit(BaseModel):
    """Plantilla G."""

    number: int
    cost_usd: Decimal
    next_box_number: int
    next_box_cost_usd: Decimal
    difference_usd: Decimal
    final_cost_usd: Decimal
    sales_usd: Decimal
    profit_usd: Decimal
    broken_eggs: int
    broken_loss_usd: Decimal
    broken_percent: Decimal


class SheetRow(BaseModel):
    day: date
    rate: Decimal | None
    boxes: int
    cartons: int
    halves: int
    units: int
    shared_sale_eggs: int
    broken: int
    other_losses: int
    eggs: int
    amount_usd: Decimal
    amount_bs: Decimal
    payment_methods: list[PaymentMethod]


class BoxSheet(BaseModel):
    """Plantilla C: header, one row per day and the footer totals."""

    box: BoxView
    egg_cost_usd: Decimal
    rows: list[SheetRow]
    total_eggs: int
    total_broken: int
    total_sales_usd: Decimal
    profit: BoxProfit | None


def box_view(box: Box, remaining: int) -> BoxView:
    return BoxView(
        number=box.number,
        status=box.status,
        purchase_day=box.purchase.day,
        cost_usd=box.cost_usd,
        box_price=box.box_price,
        carton_price=box.carton_price,
        half_price=box.half_price,
        unit_price=box.unit_price,
        remaining_eggs=remaining,
        opened_on=box.opened_on,
        finished_on=box.finished_on,
    )


async def get_box(session: AsyncSession, number: int) -> Box:
    box = await session.scalar(
        select(Box).where(Box.number == number).options(selectinload(Box.purchase))
    )
    if box is None:
        raise DomainError(f"No existe la Caja {number}.")
    return box


async def views_of(session: AsyncSession, boxes: list[Box]) -> list[BoxView]:
    used = await used_eggs(session, [box.id for box in boxes])
    return [box_view(box, rules.EGGS_PER_BOX - used.get(box.id, 0)) for box in boxes]


async def view_of(session: AsyncSession, box: Box) -> BoxView:
    return (await views_of(session, [box]))[0]


async def _movements(session: AsyncSession, box: Box) -> list[EggMovement]:
    rows = await session.scalars(
        select(EggMovement)
        .where(EggMovement.box_id == box.id)
        .options(selectinload(EggMovement.sale).selectinload(Sale.movements))
        .order_by(EggMovement.day, EggMovement.id)
    )
    return list(rows)


async def next_box(session: AsyncSession, box: Box) -> Box | None:
    return await session.scalar(select(Box).where(Box.number == box.number + 1))


def profit_of(box: Box, following: Box, movements: list[EggMovement]) -> BoxProfit:
    sales = sum(
        (m.amount_usd or Decimal(0) for m in movements if m.kind == MovementKind.SALE), Decimal(0)
    )
    broken = sum(m.eggs for m in movements if m.kind == MovementKind.BROKEN)
    figures = rules.box_profit(sales, box.cost_usd, following.cost_usd)
    return BoxProfit(
        number=box.number,
        cost_usd=box.cost_usd,
        next_box_number=following.number,
        next_box_cost_usd=following.cost_usd,
        difference_usd=figures.difference,
        final_cost_usd=figures.final_cost,
        sales_usd=sales,
        profit_usd=figures.profit,
        broken_eggs=broken,
        broken_loss_usd=rules.broken_loss(broken, box.cost_usd),
        broken_percent=rules.broken_percent(broken),
    )


async def profit_if_closed(
    session: AsyncSession, box: Box, movements: list[EggMovement]
) -> BoxProfit | None:
    if box.status not in (BoxStatus.FINISHED, BoxStatus.SETTLED):
        return None
    following = await next_box(session, box)
    return None if following is None else profit_of(box, following, movements)


async def box_profit(session: AsyncSession, number: int) -> BoxProfit:
    box = await get_box(session, number)
    movements = await _movements(session, box)
    if box.status not in (BoxStatus.FINISHED, BoxStatus.SETTLED):
        left = rules.EGGS_PER_BOX - sum(m.eggs for m in movements)
        raise DomainError(
            f"La Caja {number} todavía tiene {left} huevos. "
            "Su ganancia se calcula cuando se acabe y ya esté comprada la siguiente."
        )
    following = await next_box(session, box)
    if following is None:
        raise DomainError(
            f"Todavía no se compró la Caja {number + 1}. Hasta entonces lo vendido de la "
            f"Caja {number} es dinero de la próxima caja y no se toca."
        )
    return profit_of(box, following, movements)


def _sale_part_bs(movement: EggMovement) -> Decimal:
    sale = movement.sale
    assert sale is not None
    parts = rules.split_by_weights(
        sale.amount_bs, [m.amount_usd or Decimal(0) for m in sale.movements]
    )
    return parts[[m.id for m in sale.movements].index(movement.id)]


def _sheet_rows(movements: list[EggMovement]) -> list[SheetRow]:
    by_day: dict[date, list[EggMovement]] = defaultdict(list)
    for movement in movements:
        by_day[movement.day].append(movement)
    rows: list[SheetRow] = []
    for day, day_movements in by_day.items():
        sale_parts = [m for m in day_movements if m.kind == MovementKind.SALE]
        whole = [m.sale for m in sale_parts if m.sale and len(m.sale.movements) == 1]
        rows.append(
            SheetRow(
                day=day,
                rate=sale_parts[0].sale.rate if sale_parts and sale_parts[0].sale else None,
                boxes=sum(s.boxes for s in whole),
                cartons=sum(s.cartons for s in whole),
                halves=sum(s.halves for s in whole),
                units=sum(s.units for s in whole),
                shared_sale_eggs=sum(
                    m.eggs for m in sale_parts if m.sale and len(m.sale.movements) > 1
                ),
                broken=sum(m.eggs for m in day_movements if m.kind == MovementKind.BROKEN),
                other_losses=sum(
                    m.eggs
                    for m in day_movements
                    if m.kind in (MovementKind.GIFT, MovementKind.SHRINKAGE)
                ),
                eggs=sum(m.eggs for m in day_movements),
                amount_usd=sum((m.amount_usd or Decimal(0) for m in sale_parts), Decimal(0)),
                amount_bs=sum((_sale_part_bs(m) for m in sale_parts), Decimal(0)),
                payment_methods=sorted(
                    {m.sale.payment_method for m in sale_parts if m.sale},
                    key=list(PaymentMethod).index,
                ),
            )
        )
    return rows


async def box_sheet(session: AsyncSession, number: int) -> BoxSheet:
    box = await get_box(session, number)
    movements = await _movements(session, box)
    rows = _sheet_rows(movements)
    total_eggs = sum(row.eggs for row in rows)
    return BoxSheet(
        box=box_view(box, rules.EGGS_PER_BOX - total_eggs),
        egg_cost_usd=rules.four_places(rules.egg_cost(box.cost_usd)),
        rows=rows,
        total_eggs=total_eggs,
        total_broken=sum(row.broken for row in rows),
        total_sales_usd=sum((row.amount_usd for row in rows), Decimal(0)),
        profit=await profit_if_closed(session, box, movements),
    )


async def list_boxes(session: AsyncSession, include_settled: bool = False) -> list[BoxView]:
    query = select(Box).options(selectinload(Box.purchase)).order_by(Box.number)
    if not include_settled:
        query = query.where(Box.status != BoxStatus.SETTLED)
    return await views_of(session, list(await session.scalars(query)))


async def boxes_page(
    session: AsyncSession, request: PageRequest, include_settled: bool = False
) -> Page[BoxView]:
    query = select(Box).options(selectinload(Box.purchase)).order_by(Box.number.desc())
    if not include_settled:
        query = query.where(Box.status != BoxStatus.SETTLED)
    rows, total = await fetch_page(session, query, request)
    return Page[BoxView].of(await views_of(session, rows), total, request)
