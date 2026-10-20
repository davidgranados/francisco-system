"""Web ledger login: a one-time code sent by the Telegram bot, then a cookie session."""

import hashlib
import logging
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import identity
from app.agent.identity import Actor
from app.config import DevUser
from app.models import LoginCode, Partner, WebSession

logger = logging.getLogger(__name__)

CODE_LIFETIME = timedelta(minutes=10)
RESEND_AFTER = timedelta(seconds=60)
MAX_TRIES = 5
SESSION_LIFETIME = timedelta(days=90)

CODE_MESSAGE = (
    "Su código para entrar a las cuentas es {code}. Vence en 10 minutos. "
    "Si usted no lo pidió, no haga nada."
)
UNKNOWN_PERSON = "No encuentro a «{name}» entre las personas que pueden entrar."
TOO_SOON = (
    "Ya le enviamos un código hace menos de un minuto. Revise Telegram, o espere un momento "
    "y pida otro."
)
NOT_DELIVERED = (
    "No pudimos enviarle el código por Telegram. Abra el chat con el bot, toque «Iniciar» "
    "y vuelva a pedirlo."
)
NO_CODE = "No hay un código pendiente para usted. Pida uno nuevo."
EXPIRED = "El código venció. Pida uno nuevo."
USED_UP = "Ese código ya no sirve: se equivocó cinco veces. Pida uno nuevo."
WRONG = "El código no es correcto. {left}"
NOT_LOGGED_IN = "Su sesión no es válida o ya venció. Entre de nuevo."


class Role(StrEnum):
    PARTNER = "partner"
    DEVELOPER = "developer"


class Person(BaseModel):
    name: str


class Me(BaseModel):
    name: str
    role: Role


class CodeSent(BaseModel):
    expires_in_seconds: int


class CodeSender(Protocol):
    async def send_message(self, chat_id: int, text: str) -> None: ...


class AuthRefusal(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UnknownPerson(AuthRefusal):
    pass


class CodeTooSoon(AuthRefusal):
    pass


class CodeNotDelivered(AuthRefusal):
    pass


class CodeRejected(AuthRefusal):
    pass


@dataclass(frozen=True)
class LoggedIn:
    me: Me
    token: str


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def me_of(actor: Actor) -> Me:
    return Me(name=actor.name, role=Role.PARTNER if actor.is_partner else Role.DEVELOPER)


async def _candidates(session: AsyncSession, dev_users: Sequence[DevUser]) -> list[Actor]:
    """Who can log in, by name: active partners with Telegram first, then developers."""
    partners = await session.scalars(
        select(Partner)
        .where(Partner.active, Partner.telegram_user_id.is_not(None))
        .order_by(Partner.id)
    )
    actors = [Actor(p.telegram_user_id, p.name, p.id) for p in partners if p.telegram_user_id]
    actors += [Actor(dev.telegram_user_id, dev.name) for dev in dev_users]
    unique: dict[str, Actor] = {}
    for actor in actors:
        unique.setdefault(actor.name.strip().lower(), actor)
    return list(unique.values())


async def people(session: AsyncSession, dev_users: Sequence[DevUser]) -> list[Person]:
    actors = await _candidates(session, dev_users)
    return [Person(name=a.name) for a in sorted(actors, key=lambda a: a.name.lower())]


async def _person(session: AsyncSession, name: str, dev_users: Sequence[DevUser]) -> Actor | None:
    wanted = name.strip().lower()
    for actor in await _candidates(session, dev_users):
        if actor.name.strip().lower() == wanted:
            return actor
    return None


async def request_code(
    session: AsyncSession,
    name: str,
    now: datetime,
    sender: CodeSender | None,
    dev_users: Sequence[DevUser],
) -> CodeSent:
    """Replace the person's code with a new one and send it; `sender` None logs it instead."""
    person = await _person(session, name, dev_users)
    if person is None:
        raise UnknownPerson(UNKNOWN_PERSON.format(name=name.strip()))
    code = f"{secrets.randbelow(1_000_000):06d}"
    fresh = {
        "code_hash": _sha256(code),
        "sent_at": now,
        "expires_at": now + CODE_LIFETIME,
        "tries": 0,
    }
    stored = await session.scalar(
        insert(LoginCode)
        .values(telegram_user_id=person.telegram_user_id, **fresh)
        .on_conflict_do_update(
            index_elements=[LoginCode.telegram_user_id],
            set_=fresh,
            where=LoginCode.sent_at <= now - RESEND_AFTER,
        )
        .returning(LoginCode.telegram_user_id)
    )
    if stored is None:
        raise CodeTooSoon(TOO_SOON)
    if sender is None:
        logger.warning("login code for %s: %s", person.name, code)
    else:
        try:
            await sender.send_message(person.telegram_user_id, CODE_MESSAGE.format(code=code))
        except Exception as error:
            logger.warning("login code for %s not delivered: %r", person.name, error)
            raise CodeNotDelivered(NOT_DELIVERED) from error
    return CodeSent(expires_in_seconds=int(CODE_LIFETIME.total_seconds()))


def _tries_left(tries: int) -> str:
    left = MAX_TRIES - tries
    return "Le queda 1 intento." if left == 1 else f"Le quedan {left} intentos."


async def login(
    session: AsyncSession, name: str, code: str, now: datetime, dev_users: Sequence[DevUser]
) -> LoggedIn:
    """Open a session when `code` matches; a wrong code counts a try, and the fifth kills it."""
    person = await _person(session, name, dev_users)
    if person is None:
        raise CodeRejected(NO_CODE)
    stored = await session.scalar(
        select(LoginCode)
        .where(LoginCode.telegram_user_id == person.telegram_user_id)
        .with_for_update()
    )
    if stored is None:
        raise CodeRejected(NO_CODE)
    if stored.tries >= MAX_TRIES:
        raise CodeRejected(USED_UP)
    if now >= stored.expires_at:
        raise CodeRejected(EXPIRED)
    if not secrets.compare_digest(_sha256(code.strip()), stored.code_hash):
        stored.tries += 1
        raise CodeRejected(
            USED_UP if stored.tries >= MAX_TRIES else WRONG.format(left=_tries_left(stored.tries))
        )
    await session.delete(stored)
    await session.execute(delete(WebSession).where(WebSession.expires_at <= now))
    token = secrets.token_urlsafe(32)
    session.add(
        WebSession(
            token_hash=_sha256(token),
            telegram_user_id=person.telegram_user_id,
            expires_at=now + SESSION_LIFETIME,
        )
    )
    return LoggedIn(me_of(person), token)


async def actor_for(
    session: AsyncSession, token: str, now: datetime, dev_users: Sequence[DevUser]
) -> Actor | None:
    """Who holds this session cookie, if it is unexpired and they may still log in."""
    stored = await session.get(WebSession, _sha256(token))
    if stored is None or now >= stored.expires_at:
        return None
    return await identity.resolve(session, stored.telegram_user_id, dev_users)


async def logout(session: AsyncSession, token: str) -> None:
    await session.execute(delete(WebSession).where(WebSession.token_hash == _sha256(token)))
