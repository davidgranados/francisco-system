import secrets
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Query, Request, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DevUser, settings
from app.db import session_scope
from app.services import web_auth
from app.services.pages import PageRequest

SESSION_COOKIE = "fs_session"
MISSING_KEY = "Falta la cabecera X-API-Key o no es válida."
READ_METHODS = frozenset({"GET", "HEAD"})

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

Session = Annotated[AsyncSession, Depends(session_scope, scope="function")]
ApiKey = Annotated[str | None, Security(api_key_header)]
SessionToken = Annotated[str | None, Cookie(alias=SESSION_COOKIE, include_in_schema=False)]


def current_time() -> datetime:
    return datetime.now(UTC)


def dev_users() -> Sequence[DevUser]:
    return settings.dev_users


Now = Annotated[datetime, Depends(current_time)]
DevUsers = Annotated[Sequence[DevUser], Depends(dev_users)]


def key_holder(key: str | None) -> str | None:
    """The name of whoever holds the key, or None when it is not a known key."""
    if key:
        for known, name in settings.api_key_map.items():
            if secrets.compare_digest(key.encode(), known.encode()):
                return name
    return None


async def require_access(
    request: Request,
    session: Session,
    now: Now,
    developers: DevUsers,
    key: ApiKey = None,
    token: SessionToken = None,
) -> str:
    """An API key opens everything; a web session cookie only reads."""
    holder = key_holder(key)
    if holder is not None:
        return holder
    if token and request.method in READ_METHODS:
        actor = await web_auth.actor_for(session, token, now, developers)
        if actor is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, web_auth.NOT_LOGGED_IN)
        return actor.name
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, MISSING_KEY)


def page_request(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PageRequest:
    return PageRequest(page=page, page_size=page_size)


Paging = Annotated[PageRequest, Depends(page_request)]
