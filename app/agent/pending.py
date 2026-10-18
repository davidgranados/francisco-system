"""Actions waiting for the Confirmar button: one per chat, single use, expiring."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PendingAction

TTL = timedelta(minutes=15)


class Outcome(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    CHANGED = "changed"
    FAILED = "failed"


def now() -> datetime:
    return datetime.now(UTC)


async def create(
    session: AsyncSession,
    *,
    chat_id: int,
    partner_id: int,
    tool: str,
    arguments: dict[str, Any],
    preview: Any,
) -> int:
    """Store the action; an older one still waiting in the same chat can no longer be used."""
    moment = now()
    await session.execute(
        update(PendingAction)
        .where(PendingAction.chat_id == chat_id, PendingAction.resolved_at.is_(None))
        .values(resolved_at=moment, outcome=Outcome.SUPERSEDED)
    )
    action = PendingAction(
        chat_id=chat_id,
        partner_id=partner_id,
        tool=tool,
        arguments=arguments,
        preview=preview,
        expires_at=moment + TTL,
    )
    session.add(action)
    await session.flush()
    return action.id


@dataclass(frozen=True)
class Refusal:
    message: str
    final: bool = True
    """False when the action is still usable by its own partner, so its buttons stay."""


NOT_YOURS = "Solo el socio que pidió esta operación puede confirmarla o cancelarla."
USED = "Esa operación ya se confirmó, se canceló o fue reemplazada por otra más nueva."
EXPIRED = "Pasaron más de 15 minutos y esa vista previa venció. Pídala de nuevo."


async def claim(
    session: AsyncSession, action_id: int, chat_id: int, partner_id: int
) -> PendingAction | Refusal:
    """Lock the action and mark it used; a second press, or anyone else, gets a refusal."""
    action = await session.scalar(
        select(PendingAction).where(PendingAction.id == action_id).with_for_update()
    )
    if action is None or action.chat_id != chat_id:
        return Refusal(USED)
    if action.partner_id != partner_id:
        return Refusal(NOT_YOURS, final=False)
    if action.resolved_at is not None:
        return Refusal(USED)
    action.resolved_at = now()
    if action.expires_at <= action.resolved_at:
        action.outcome = Outcome.EXPIRED
        return Refusal(EXPIRED)
    return action
