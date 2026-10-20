"""Money that moves without a purchase, sale, expense, aporte or cierre behind it."""

from datetime import date
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import today
from app.db import lock_inventory
from app.domain import rules
from app.domain.errors import DomainError
from app.domain.types import Fund, TransferKind
from app.models import FundTransfer
from app.services import funds, partners
from app.services.pages import Page, PageRequest, fetch_page
from app.services.purchases import VoidInput

CENT = Decimal("0.01")


class TransferInput(BaseModel):
    kind: TransferKind
    from_fund: Fund
    to_fund: Fund | None = Field(default=None, description="Solo en un traspaso entre fondos")
    partner: str | None = Field(default=None, description="Solo cuando el dinero sale a un socio")
    amount_usd: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    day: date | None = Field(default=None, description="Fecha del movimiento; por defecto hoy")
    note: str | None = None

    @model_validator(mode="after")
    def shape(self) -> Self:
        if self.kind == TransferKind.BETWEEN_FUNDS:
            if self.to_fund is None or self.partner is not None:
                raise ValueError("un traspaso va de un fondo a otro, sin socio")
            if self.to_fund == self.from_fund:
                raise ValueError("el fondo de origen y el de destino son el mismo")
            return self
        if self.to_fund is not None or self.partner is None:
            raise ValueError("una devolución de aporte o un retiro de utilidades va a un socio")
        if self.kind == TransferKind.CONTRIBUTION_RETURN and self.from_fund != Fund.CAPITAL:
            raise ValueError("un aporte se devuelve solo desde el capital")
        return self


class TransferView(BaseModel):
    id: int
    day: date
    kind: TransferKind
    from_fund: Fund
    to_fund: Fund | None
    partner: str | None
    amount_usd: Decimal
    note: str | None
    voided: bool
    void_reason: str | None


def _view(transfer: FundTransfer) -> TransferView:
    return TransferView(
        id=transfer.id,
        day=transfer.day,
        kind=transfer.kind,
        from_fund=transfer.from_fund,
        to_fund=transfer.to_fund,
        partner=transfer.partner.name if transfer.partner else None,
        amount_usd=transfer.amount_usd,
        note=transfer.note,
        voided=transfer.voided,
        void_reason=transfer.void_reason,
    )


async def _check_returnable(session: AsyncSession, partner: str, amount: Decimal) -> None:
    left = dict(await funds.contributed(session)).get(partner, Decimal("0.00"))
    if amount > left:
        raise DomainError(
            f"A {partner} se le pueden devolver hasta {rules.format_usd(left)}: es lo que "
            "aportó menos lo que ya se le devolvió. Más que eso sería un retiro de utilidades."
        )


async def move_money(session: AsyncSession, data: TransferInput) -> TransferView:
    """Record the move if the fund it takes from stays covered on every day from its date on."""
    await lock_inventory(session)
    day = data.day or today()
    if day > today():
        raise DomainError(f"La fecha del movimiento, {day:%d/%m/%Y}, es futura.")
    partner = await partners.find_by_name(session, data.partner) if data.partner else None
    if partner is not None and data.kind == TransferKind.CONTRIBUTION_RETURN:
        await _check_returnable(session, partner.name, data.amount_usd)
    transfer = FundTransfer(
        day=day,
        kind=data.kind,
        from_fund=data.from_fund,
        to_fund=data.to_fund,
        partner=partner,
        amount_usd=data.amount_usd.quantize(CENT),
        note=data.note,
    )
    await funds.ensure_covered(session, funds.Operation.TRANSFER, funds.transfer_postings(transfer))
    session.add(transfer)
    await session.flush()
    return _view(transfer)


async def void_transfer(session: AsyncSession, transfer_id: int, data: VoidInput) -> TransferView:
    """Undo a move; refused when the fund that received it already spent the money."""
    await lock_inventory(session)
    transfer = await session.get(FundTransfer, transfer_id)
    if transfer is None:
        raise DomainError(f"No existe el movimiento de dinero {transfer_id}.")
    if transfer.voided:
        raise DomainError(f"El movimiento de dinero {transfer_id} ya estaba anulado.")
    undone = [
        funds.Posting(p.day, p.fund, -p.amount_usd, p.kind)
        for p in funds.transfer_postings(transfer)
    ]
    await funds.ensure_covered(session, funds.Operation.TRANSFER, undone)
    transfer.voided = True
    transfer.void_reason = data.reason
    await session.flush()
    return _view(transfer)


def _newest_first() -> Select[tuple[FundTransfer]]:
    return select(FundTransfer).order_by(FundTransfer.day.desc(), FundTransfer.id.desc())


async def list_transfers(session: AsyncSession, limit: int = 20) -> list[TransferView]:
    rows = await session.scalars(_newest_first().limit(limit))
    return [_view(transfer) for transfer in rows]


async def transfers_page(session: AsyncSession, request: PageRequest) -> Page[TransferView]:
    rows, total = await fetch_page(session, _newest_first(), request)
    return Page[TransferView].of([_view(transfer) for transfer in rows], total, request)
