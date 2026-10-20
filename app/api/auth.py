from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.deps import SESSION_COOKIE, DevUsers, Now, Session, SessionToken
from app.config import settings
from app.services import web_auth
from app.services.web_auth import CodeSender, CodeSent, Me, Person

router = APIRouter(prefix="/api/auth", tags=["entrada"])

STATUS: dict[type[web_auth.AuthRefusal], int] = {
    web_auth.UnknownPerson: status.HTTP_404_NOT_FOUND,
    web_auth.CodeTooSoon: status.HTTP_429_TOO_MANY_REQUESTS,
    web_auth.CodeNotDelivered: status.HTTP_503_SERVICE_UNAVAILABLE,
    web_auth.CodeRejected: status.HTTP_401_UNAUTHORIZED,
}


class CodeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class LoginInput(CodeRequest):
    code: str = Field(min_length=1, max_length=12)


def code_sender(request: Request) -> CodeSender | None:
    """The Telegram bridge; None when Telegram is not configured, so the code is logged."""
    if not settings.telegram_bot_token:
        return None
    bridge: CodeSender | None = getattr(request.app.state, "telegram", None)
    if bridge is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, web_auth.NOT_DELIVERED)
    return bridge


def _refused(error: web_auth.AuthRefusal) -> HTTPException:
    return HTTPException(STATUS[type(error)], error.message)


@router.get("/people")
async def people(session: Session, developers: DevUsers) -> list[Person]:
    return await web_auth.people(session, developers)


@router.post("/code", status_code=status.HTTP_202_ACCEPTED)
async def request_code(
    request: Request, session: Session, data: CodeRequest, now: Now, developers: DevUsers
) -> CodeSent:
    sender = code_sender(request)
    try:
        return await web_auth.request_code(session, data.name, now, sender, developers)
    except web_auth.AuthRefusal as error:
        raise _refused(error) from error


@router.post(
    "/login",
    response_model=Me,
    responses={401: {"description": "Código incorrecto, vencido o usado"}},
)
async def login(
    request: Request,
    response: Response,
    session: Session,
    data: LoginInput,
    now: Now,
    developers: DevUsers,
) -> Me | JSONResponse:
    try:
        logged_in = await web_auth.login(session, data.name, data.code, now, developers)
    except web_auth.CodeRejected as error:
        # Returned, not raised: the request transaction must commit the counted try.
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": error.message}
        )
    response.set_cookie(
        SESSION_COOKIE,
        logged_in.token,
        max_age=int(web_auth.SESSION_LIFETIME.total_seconds()),
        path="/",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="lax",
    )
    return logged_in.me


@router.get("/me")
async def me(session: Session, now: Now, developers: DevUsers, token: SessionToken = None) -> Me:
    actor = await web_auth.actor_for(session, token, now, developers) if token else None
    if actor is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, web_auth.NOT_LOGGED_IN)
    return web_auth.me_of(actor)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, session: Session, token: SessionToken = None) -> Response:
    if token:
        await web_auth.logout(session, token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="lax",
    )
    return response
