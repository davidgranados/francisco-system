"""The egg ledger: remaining eggs per box, FIFO consumption and the box state machine."""

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import DomainError
from app.domain.rules import (
    EGGS_PER_BOX,
    allocate_fifo,
    box_status_for,
    check_box_transition,
    is_fifo_sequence,
    split_by_weights,
)
from app.domain.types import BoxStatus, MovementKind
from app.models import Box, EggMovement, InventoryCount, Sale

UNSETTLED_WITH_EGGS = (BoxStatus.STOCKED, BoxStatus.OPEN)


async def used_eggs(session: AsyncSession, box_ids: Iterable[int] | None = None) -> dict[int, int]:
    query = select(EggMovement.box_id, func.sum(EggMovement.eggs)).group_by(EggMovement.box_id)
    if box_ids is not None:
        query = query.where(EggMovement.box_id.in_(list(box_ids)))
    return {box_id: int(total) for box_id, total in (await session.execute(query)).all()}


async def boxes_with_eggs(session: AsyncSession) -> list[tuple[Box, int]]:
    """Boxes that still hold eggs, oldest first, with how many they hold."""
    boxes = list(
        await session.scalars(
            select(Box).where(Box.status.in_(UNSETTLED_WITH_EGGS)).order_by(Box.number)
        )
    )
    used = await used_eggs(session, [box.id for box in boxes])
    holdings = [(box, EGGS_PER_BOX - used.get(box.id, 0)) for box in boxes]
    return [(box, remaining) for box, remaining in holdings if remaining > 0]


def move_box(box: Box, target: BoxStatus, day: date | None) -> None:
    check_box_transition(box.status, target)
    if target == box.status:
        return
    box.status = target
    if target == BoxStatus.STOCKED:
        box.opened_on = None
        box.finished_on = None
    elif target == BoxStatus.OPEN:
        box.opened_on = box.opened_on or day
        box.finished_on = None
    elif target == BoxStatus.FINISHED:
        box.opened_on = box.opened_on or day
        box.finished_on = day


async def take_eggs(
    session: AsyncSession,
    eggs: int,
    day: date,
    kind: MovementKind,
    *,
    sale: Sale | None = None,
    count: InventoryCount | None = None,
    note: str | None = None,
) -> list[EggMovement]:
    """Record `eggs` leaving the oldest boxes first, opening and finishing boxes as they empty."""
    holdings = await boxes_with_eggs(session)
    taken = allocate_fifo(eggs, holdings)
    remaining = {box.id: left for box, left in holdings}
    amounts: list[Decimal | None] = (
        list(split_by_weights(sale.amount_usd, [part for _, part in taken]))
        if sale is not None
        else [None] * len(taken)
    )
    movements: list[EggMovement] = []
    for (box, part), amount in zip(taken, amounts, strict=True):
        movement = EggMovement(
            box=box, day=day, kind=kind, eggs=part, amount_usd=amount, sale=sale, note=note
        )
        if count is not None:
            movement.count_id = count.id
        session.add(movement)
        left = remaining[box.id] - part
        # Flush box by box, oldest first: the single-open index must see the old box close first.
        move_box(box, BoxStatus.FINISHED if left == 0 else BoxStatus.OPEN, day)
        await session.flush()
        movements.append(movement)
    return movements


async def release_movements(session: AsyncSession, movements: list[EggMovement]) -> None:
    """Delete movements and return their boxes to the status the remaining ledger implies."""
    boxes = {movement.box.id: movement.box for movement in movements}
    if any(box.status == BoxStatus.SETTLED for box in boxes.values()):
        numbers = ", ".join(
            str(box.number) for box in boxes.values() if box.status == BoxStatus.SETTLED
        )
        raise DomainError(f"No se puede: la caja {numbers} ya entró en un cierre y se repartió.")
    released = {movement.id for movement in movements}
    leftover = await session.execute(
        select(EggMovement.box_id, func.sum(EggMovement.eggs), func.count())
        .where(EggMovement.box_id.in_(list(boxes)), EggMovement.id.not_in(released))
        .group_by(EggMovement.box_id)
    )
    still_used = {box_id: (int(total), int(n)) for box_id, total, n in leftover.all()}
    targets = {
        box_id: box_status_for(
            EGGS_PER_BOX - still_used.get(box_id, (0, 0))[0], box_id in still_used
        )
        for box_id in boxes
    }
    statuses = dict((await session.execute(select(Box.id, Box.status))).all())
    statuses.update(targets)
    numbers = {box.id: box.number for box in boxes.values()}
    numbers.update(dict((await session.execute(select(Box.id, Box.number))).all()))
    sequence = [statuses[box_id] for box_id in sorted(statuses, key=numbers.__getitem__)]
    if not is_fifo_sequence(sequence):
        raise DomainError(
            "No se puede anular: después de esa venta ya se siguió vendiendo de otra caja, "
            "y quedarían dos cajas abiertas o una caja vieja sin terminar. Anule primero las "
            "ventas posteriores o registre la corrección como huevos rotos o regalados."
        )
    for movement in movements:
        await session.delete(movement)
    await session.flush()
    ordered = sorted(targets.items(), key=lambda item: item[1] == BoxStatus.OPEN)
    for box_id, target in ordered:
        move_box(boxes[box_id], target, None)
        await session.flush()
