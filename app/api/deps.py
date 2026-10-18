import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import session_scope

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(key: Annotated[str | None, Security(api_key_header)]) -> str:
    """Return the name of whoever holds the key."""
    if key:
        for known, name in settings.api_key_map.items():
            if secrets.compare_digest(key.encode(), known.encode()):
                return name
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falta la cabecera X-API-Key o no es válida.")


Session = Annotated[AsyncSession, Depends(session_scope, scope="function")]
