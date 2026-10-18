"""Who is talking to the bot: a partner or a developer, resolved once per update."""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DevUser
from app.services import partners


@dataclass(frozen=True)
class Actor:
    """A Telegram user the bot answers; `partner_id` is None for a developer."""

    telegram_user_id: int
    name: str
    partner_id: int | None = None

    @property
    def is_partner(self) -> bool:
        return self.partner_id is not None

    @property
    def introduction(self) -> str:
        """How the model is told who writes; a developer must never be read as a partner."""
        if self.is_partner:
            return self.name
        return f"{self.name} (desarrollador, no es socio: «yo» no es ningún socio)"


async def resolve(
    session: AsyncSession, telegram_user_id: int, dev_users: Sequence[DevUser]
) -> Actor | None:
    """An active partner first, then a configured developer; anyone else gets None."""
    partner = await partners.by_telegram_id(session, telegram_user_id)
    if partner is not None:
        return Actor(telegram_user_id, partner.name, partner.id)
    for dev in dev_users:
        if dev.telegram_user_id == telegram_user_id:
            return Actor(telegram_user_id, dev.name)
    return None
