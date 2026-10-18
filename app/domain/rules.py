"""Business rules of the egg notebook, as pure functions over Decimal and int.

Each rounding choice is the one that makes the notebook's worked examples come out exact;
see docs/diseno.md, "Reglas resueltas".
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from app.domain.errors import DomainError
from app.domain.types import BoxStatus, Presentation

CENT = Decimal("0.01")
NICKEL = Decimal("0.05")
FOUR_PLACES = Decimal("0.0001")
EGGS_PER_BOX = int(Presentation.BOX)
CARTONS_PER_BOX = EGGS_PER_BOX // Presentation.CARTON
HALVES_PER_BOX = EGGS_PER_BOX // Presentation.HALF


def round_cents(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def ceil_to(amount: Decimal, step: Decimal) -> Decimal:
    return ((amount / step).to_integral_value(rounding=ROUND_CEILING) * step).quantize(CENT)


def four_places(amount: Decimal) -> Decimal:
    return amount.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Prices:
    box: Decimal
    carton: Decimal
    half: Decimal
    unit: Decimal


def prices_from_cost(cost: Decimal, markup: Decimal) -> Prices:
    box = ceil_to(cost * (1 + markup), CENT)
    return Prices(
        box=box,
        carton=ceil_to(box / CARTONS_PER_BOX, NICKEL),
        half=ceil_to(box / HALVES_PER_BOX, NICKEL),
        unit=ceil_to(box / EGGS_PER_BOX, CENT),
    )


def eggs_in(cartons: int, halves: int, units: int) -> int:
    return cartons * Presentation.CARTON + halves * Presentation.HALF + units * Presentation.UNIT


def list_amount(prices: Prices, cartons: int, halves: int, units: int) -> Decimal:
    return cartons * prices.carton + halves * prices.half + units * prices.unit


def to_bs(usd: Decimal, rate: Decimal) -> Decimal:
    return round_cents(usd * rate)


def to_usd(bs: Decimal, rate: Decimal) -> Decimal:
    return round_cents(bs / rate)


def split_by_weights(total: Decimal, weights: Sequence[int | Decimal]) -> list[Decimal]:
    """Split an amount proportionally to the weights; the rounding remainder goes last."""
    whole = sum(weights, Decimal(0))
    parts = [round_cents(total * weight / whole) for weight in weights[:-1]]
    return [*parts, total - sum(parts, Decimal(0))]


def split_shares(total: Decimal, shares: Sequence[Decimal]) -> list[Decimal]:
    """Each share to the cent; the cent that keeps the sum exact goes to the largest share."""
    parts = [round_cents(total * share) for share in shares]
    largest = max(range(len(shares)), key=lambda index: shares[index])
    parts[largest] += total - sum(parts, Decimal(0))
    return parts


def allocate_fifo[K](eggs: int, available: Sequence[tuple[K, int]]) -> list[tuple[K, int]]:
    """Take eggs from the oldest holdings first. `available` is ordered oldest first."""
    total = sum(remaining for _, remaining in available)
    if total == 0:
        raise DomainError("No hay huevos en existencia. Primero registre una compra.")
    if eggs > total:
        raise DomainError(f"No alcanza: quedan {total} huevos y se piden {eggs}.")
    taken: list[tuple[K, int]] = []
    pending = eggs
    for key, remaining in available:
        if pending == 0:
            break
        take = min(pending, remaining)
        if take:
            taken.append((key, take))
            pending -= take
    return taken


BOX_TRANSITIONS: dict[BoxStatus, frozenset[BoxStatus]] = {
    BoxStatus.STOCKED: frozenset({BoxStatus.OPEN, BoxStatus.FINISHED}),
    BoxStatus.OPEN: frozenset({BoxStatus.FINISHED, BoxStatus.STOCKED}),
    BoxStatus.FINISHED: frozenset({BoxStatus.SETTLED, BoxStatus.OPEN, BoxStatus.STOCKED}),
    BoxStatus.SETTLED: frozenset(),
}


def box_status_for(remaining: int, has_movements: bool) -> BoxStatus:
    """The status the ledger implies for a box that is not settled."""
    if remaining == 0:
        return BoxStatus.FINISHED
    if has_movements:
        return BoxStatus.OPEN
    return BoxStatus.STOCKED


_CONSUMPTION_ORDER = {
    BoxStatus.SETTLED: 0,
    BoxStatus.FINISHED: 0,
    BoxStatus.OPEN: 1,
    BoxStatus.STOCKED: 2,
}


def is_fifo_sequence(statuses_by_number: Sequence[BoxStatus]) -> bool:
    """Boxes empty strictly oldest first: done boxes, then at most one open, then untouched."""
    ranks = [_CONSUMPTION_ORDER[status] for status in statuses_by_number]
    return ranks == sorted(ranks) and ranks.count(1) <= 1


def check_box_transition(current: BoxStatus, target: BoxStatus) -> None:
    if current != target and target not in BOX_TRANSITIONS[current]:
        raise ValueError(f"box cannot go from {current} to {target}")


@dataclass(frozen=True)
class BoxProfitFigures:
    difference: Decimal
    final_cost: Decimal
    profit: Decimal


def box_profit(sales: Decimal, cost: Decimal, next_box_cost: Decimal) -> BoxProfitFigures:
    difference = next_box_cost - cost
    final_cost = cost + difference
    return BoxProfitFigures(difference=difference, final_cost=final_cost, profit=sales - final_cost)


def egg_cost(box_cost: Decimal) -> Decimal:
    return box_cost / EGGS_PER_BOX


def broken_loss(eggs: int, box_cost: Decimal) -> Decimal:
    return round_cents(eggs * box_cost / EGGS_PER_BOX)


def broken_percent(eggs: int) -> Decimal:
    return (Decimal(eggs) * 100 / EGGS_PER_BOX).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def boxes_equivalent(eggs: int) -> Decimal:
    return round_cents(Decimal(eggs) / EGGS_PER_BOX)


def average_box_cost(holdings: Sequence[tuple[Decimal, int]]) -> Decimal | None:
    """Weighted average cost per box over (box cost, eggs left) holdings."""
    eggs = sum(remaining for _, remaining in holdings)
    if eggs == 0:
        return None
    value = sum((cost * remaining / EGGS_PER_BOX for cost, remaining in holdings), Decimal(0))
    return value / (Decimal(eggs) / EGGS_PER_BOX)


def reserve_amount(
    base: Decimal, reserve_usd: Decimal | None, reserve_pct: Decimal | None
) -> Decimal:
    if reserve_usd is not None:
        return reserve_usd
    if reserve_pct is None or base <= 0:
        return Decimal("0.00")
    return round_cents(base * reserve_pct)


def format_number(amount: Decimal, places: int = 2) -> str:
    text = f"{amount:,.{places}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def format_usd(amount: Decimal) -> str:
    return f"$ {format_number(amount)}"
