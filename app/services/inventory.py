from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import today
from app.db import lock_inventory
from app.domain import rules
from app.domain.types import MovementKind
from app.models import Box, EggMovement, InventoryCount, Purchase
from app.services.boxes import BoxView, views_of
from app.services.ledger import boxes_with_eggs, take_eggs


class LossInput(BaseModel):
    kind: Literal["broken", "gift"] = Field(description="broken = rotos, gift = regalados")
    eggs: int = Field(ge=1)
    day: date | None = None
    note: str | None = None


class LossView(BaseModel):
    kind: MovementKind
    day: date
    eggs: int
    loss_usd: Decimal
    parts: list[tuple[int, int]] = Field(description="(número de caja, huevos)")
    eggs_left: int


class CountInput(BaseModel):
    counted_eggs: int = Field(ge=0, description="Huevos contados físicamente")
    day: date | None = None
    note: str | None = None


class CountView(BaseModel):
    id: int
    day: date
    expected_eggs: int
    counted_eggs: int
    difference: int
    shrinkage_parts: list[tuple[int, int]]
    notice: str | None


class StockView(BaseModel):
    total_eggs: int
    boxes_equivalent: Decimal
    boxes: list[BoxView]
    average_box_cost_usd: Decimal | None
    average_egg_cost_usd: Decimal | None


class StockRow(BaseModel):
    """One day of Plantilla D."""

    day: date
    description: str
    entered: int
    sold: int
    broken: int
    other_losses: int
    remaining_eggs: int
    remaining_boxes: Decimal
    counted: int | None
    difference: int | None


async def record_loss(session: AsyncSession, data: LossInput) -> LossView:
    await lock_inventory(session)
    day = data.day or today()
    kind = MovementKind(data.kind)
    movements = await take_eggs(session, data.eggs, day, kind, note=data.note)
    return LossView(
        kind=kind,
        day=day,
        eggs=data.eggs,
        loss_usd=sum(
            (rules.broken_loss(m.eggs, m.box.cost_usd) for m in movements), Decimal("0.00")
        ),
        parts=[(m.box.number, m.eggs) for m in movements],
        eggs_left=sum(left for _, left in await boxes_with_eggs(session)),
    )


async def record_count(session: AsyncSession, data: CountInput) -> CountView:
    """Compare a physical count with the ledger; missing eggs become shrinkage, oldest box first."""
    await lock_inventory(session)
    day = data.day or today()
    expected = sum(left for _, left in await boxes_with_eggs(session))
    difference = data.counted_eggs - expected
    count = InventoryCount(
        day=day,
        expected_eggs=expected,
        counted_eggs=data.counted_eggs,
        difference=difference,
        note=data.note,
    )
    session.add(count)
    await session.flush()
    parts: list[tuple[int, int]] = []
    if difference < 0:
        movements = await take_eggs(
            session, -difference, day, MovementKind.SHRINKAGE, count=count, note=data.note
        )
        parts = [(m.box.number, m.eggs) for m in movements]
    notice = (
        f"Se contaron {difference} huevos más de los anotados. No se agregan al inventario: "
        "revise si falta anotar una compra o si se anuló una venta por error."
        if difference > 0
        else None
    )
    return CountView(
        id=count.id,
        day=day,
        expected_eggs=expected,
        counted_eggs=data.counted_eggs,
        difference=difference,
        shrinkage_parts=parts,
        notice=notice,
    )


async def stock(session: AsyncSession) -> StockView:
    holdings = await boxes_with_eggs(session)
    total = sum(left for _, left in holdings)
    average = rules.average_box_cost([(box.cost_usd, left) for box, left in holdings])
    return StockView(
        total_eggs=total,
        boxes_equivalent=rules.boxes_equivalent(total),
        boxes=await views_of(session, [box for box, _ in holdings]),
        average_box_cost_usd=None if average is None else rules.four_places(average),
        average_egg_cost_usd=None
        if average is None
        else rules.four_places(rules.egg_cost(average)),
    )


def _describe(sold: int, broken: int, other: int, bought: list[int], counted: bool) -> str:
    parts = []
    if sold:
        parts.append("ventas")
    if bought:
        numbers = f"caja {bought[0]}" if len(bought) == 1 else f"cajas {bought[0]} a {bought[-1]}"
        parts.append(f"compra {numbers}")
    if broken:
        parts.append("rotos")
    if other:
        parts.append("merma")
    if counted:
        parts.append("conteo")
    text = " + ".join(parts)
    return text[:1].upper() + text[1:]


async def stock_ledger(session: AsyncSession, date_from: date, date_to: date) -> list[StockRow]:
    """Plantilla D: per day, what came in, what left and what remains."""
    boxes = await session.execute(
        select(Purchase.day, Box.number).select_from(Box).join(Box.purchase).order_by(Box.number)
    )
    bought: dict[date, list[int]] = defaultdict(list)
    for day, number in boxes.all():
        bought[day].append(number)
    movements = await session.execute(
        select(EggMovement.day, EggMovement.kind, EggMovement.eggs).where(
            EggMovement.day <= date_to
        )
    )
    out: dict[date, dict[MovementKind, int]] = defaultdict(lambda: defaultdict(int))
    for day, kind, eggs in movements.all():
        out[day][kind] += eggs
    counts: dict[date, InventoryCount] = {
        count.day: count
        for count in await session.scalars(
            select(InventoryCount)
            .where(InventoryCount.day.between(date_from, date_to))
            .order_by(InventoryCount.id)
        )
    }
    remaining = sum(
        len(numbers) * rules.EGGS_PER_BOX for day, numbers in bought.items() if day < date_from
    ) - sum(sum(kinds.values()) for day, kinds in out.items() if day < date_from)
    rows: list[StockRow] = []
    day = date_from
    while day <= date_to:
        kinds = out.get(day, {})
        entered = len(bought.get(day, [])) * rules.EGGS_PER_BOX
        sold = kinds.get(MovementKind.SALE, 0)
        broken = kinds.get(MovementKind.BROKEN, 0)
        other = kinds.get(MovementKind.GIFT, 0) + kinds.get(MovementKind.SHRINKAGE, 0)
        count = counts.get(day)
        remaining += entered - sold - broken - other
        if entered or sold or broken or other or count:
            rows.append(
                StockRow(
                    day=day,
                    description=_describe(sold, broken, other, bought.get(day, []), bool(count)),
                    entered=entered,
                    sold=sold,
                    broken=broken,
                    other_losses=other,
                    remaining_eggs=remaining,
                    remaining_boxes=rules.boxes_equivalent(remaining),
                    counted=count.counted_eggs if count else None,
                    difference=count.difference if count else None,
                )
            )
        day += timedelta(days=1)
    return rows
