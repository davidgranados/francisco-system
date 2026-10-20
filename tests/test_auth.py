import logging
import re
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import httpx
import pytest

from app.api.deps import current_time, dev_users
from app.config import DevUser, settings
from app.main import app
from app.services import partners
from tests.conftest import Call

KEY = {"X-API-Key": "clave-de-prueba"}
STOCK = "/api/v1/inventory/stock"


class FakeTelegram:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.failure: Exception | None = None

    async def send_message(self, chat_id: int, text: str) -> None:
        if self.failure is not None:
            raise self.failure
        self.sent.append((chat_id, text))

    def last_code(self) -> str:
        match = re.search(r"\b(\d{6})\b", self.sent[-1][1])
        assert match, self.sent[-1][1]
        return match.group(1)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def clock() -> Iterator[Clock]:
    clock = Clock()
    app.dependency_overrides[current_time] = lambda: clock.now
    app.dependency_overrides[dev_users] = lambda: (DevUser("Dev", 999),)
    yield clock
    app.dependency_overrides.clear()


@pytest.fixture
def telegram(monkeypatch: pytest.MonkeyPatch) -> FakeTelegram:
    fake = FakeTelegram()
    monkeypatch.setattr(settings, "telegram_bot_token", "token")
    monkeypatch.setattr(app.state, "telegram", fake, raising=False)
    return fake


@pytest.fixture
async def client(clock: Clock, two_partners: None) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _log_in(client: httpx.AsyncClient, telegram: FakeTelegram, name: str) -> httpx.Response:
    assert (await client.post("/api/auth/code", json={"name": name})).status_code == 202
    return await client.post("/api/auth/login", json={"name": name, "code": telegram.last_code()})


async def test_a_partner_logs_in_with_the_code_the_bot_sent(
    client: httpx.AsyncClient, telegram: FakeTelegram
) -> None:
    people = await client.get("/api/auth/people")
    assert people.json() == [{"name": "Dev"}, {"name": "Socio A"}, {"name": "Socio B"}]

    sent = await client.post("/api/auth/code", json={"name": "  socio a "})
    assert (sent.status_code, sent.json()) == (202, {"expires_in_seconds": 600})
    [(chat_id, text)] = telegram.sent
    assert chat_id == 111
    assert text == (
        f"Su código para entrar a las cuentas es {telegram.last_code()}. Vence en 10 minutos. "
        "Si usted no lo pidió, no haga nada."
    )

    login = await client.post(
        "/api/auth/login", json={"name": "Socio A", "code": telegram.last_code()}
    )
    assert (login.status_code, login.json()) == (200, {"name": "Socio A", "role": "partner"})
    cookie = login.headers["set-cookie"]
    assert cookie.startswith("fs_session=")
    for attribute in ("HttpOnly", "Max-Age=7776000", "Path=/", "SameSite=lax"):
        assert attribute in cookie
    assert "Secure" not in cookie

    me = await client.get("/api/auth/me")
    assert (me.status_code, me.json()) == (200, {"name": "Socio A", "role": "partner"})

    assert (await client.post("/api/auth/logout")).status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_a_used_code_does_not_open_a_second_session(
    client: httpx.AsyncClient, telegram: FakeTelegram
) -> None:
    assert (await _log_in(client, telegram, "Socio A")).status_code == 200
    again = await client.post(
        "/api/auth/login", json={"name": "Socio A", "code": telegram.last_code()}
    )
    assert again.status_code == 401


async def test_wrong_codes_count_down_and_the_fifth_kills_the_code(
    client: httpx.AsyncClient, telegram: FakeTelegram
) -> None:
    await client.post("/api/auth/code", json={"name": "Socio A"})
    right = telegram.last_code()
    wrong = f"{(int(right) + 1) % 1_000_000:06d}"
    details = []
    for _ in range(5):
        response = await client.post("/api/auth/login", json={"name": "Socio A", "code": wrong})
        assert response.status_code == 401
        details.append(response.json()["detail"])
    assert details[0] == "El código no es correcto. Le quedan 4 intentos."
    assert details[3] == "El código no es correcto. Le queda 1 intento."
    assert "Pida uno nuevo" in details[4]

    late = await client.post("/api/auth/login", json={"name": "Socio A", "code": right})
    assert late.status_code == 401
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_an_expired_code_is_refused(
    client: httpx.AsyncClient, telegram: FakeTelegram, clock: Clock
) -> None:
    await client.post("/api/auth/code", json={"name": "Socio A"})
    clock.advance(minutes=10)
    response = await client.post(
        "/api/auth/login", json={"name": "Socio A", "code": telegram.last_code()}
    )
    assert (response.status_code, response.json()) == (
        401,
        {"detail": "El código venció. Pida uno nuevo."},
    )


async def test_a_second_code_within_a_minute_is_refused_and_a_new_one_kills_the_old(
    client: httpx.AsyncClient, telegram: FakeTelegram, clock: Clock
) -> None:
    await client.post("/api/auth/code", json={"name": "Socio A"})
    old = telegram.last_code()
    clock.advance(seconds=59)
    assert (await client.post("/api/auth/code", json={"name": "Socio A"})).status_code == 429
    assert len(telegram.sent) == 1
    assert (await client.post("/api/auth/code", json={"name": "Socio B"})).status_code == 202

    clock.advance(seconds=1)
    assert (await client.post("/api/auth/code", json={"name": "Socio A"})).status_code == 202
    new = telegram.last_code()
    refused = await client.post("/api/auth/login", json={"name": "Socio A", "code": old})
    assert refused.status_code == 401
    login = await client.post("/api/auth/login", json={"name": "Socio A", "code": new})
    assert login.status_code == 200


async def test_an_unknown_name_gets_no_code(
    client: httpx.AsyncClient, telegram: FakeTelegram
) -> None:
    response = await client.post("/api/auth/code", json={"name": "Pedro"})
    assert response.status_code == 404
    assert telegram.sent == []


async def test_a_deactivated_partner_cannot_log_in_and_loses_their_session(
    client: httpx.AsyncClient, telegram: FakeTelegram, call: Call
) -> None:
    assert (await _log_in(client, telegram, "Socio B")).status_code == 200
    assert (await client.get(STOCK)).status_code == 200

    await call(
        partners.replace_partners,
        [partners.PartnerEntry(name="Socio A", share=D("1"), telegram_user_id=111)],
    )

    assert (await client.get("/api/auth/me")).status_code == 401
    assert (await client.get(STOCK)).status_code == 401
    assert (await client.post("/api/auth/code", json={"name": "Socio B"})).status_code == 404
    names = [p["name"] for p in (await client.get("/api/auth/people")).json()]
    assert "Socio B" not in names


async def test_a_developer_logs_in(client: httpx.AsyncClient, telegram: FakeTelegram) -> None:
    login = await _log_in(client, telegram, "dev")
    assert login.json() == {"name": "Dev", "role": "developer"}
    assert telegram.sent[-1][0] == 999
    assert (await client.get(STOCK)).status_code == 200


async def test_a_session_expires_after_ninety_days(
    client: httpx.AsyncClient, telegram: FakeTelegram, clock: Clock
) -> None:
    await _log_in(client, telegram, "Socio A")
    clock.advance(days=89)
    assert (await client.get("/api/auth/me")).status_code == 200
    clock.advance(days=1)
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_the_cookie_reads_the_api_but_never_writes(
    client: httpx.AsyncClient, telegram: FakeTelegram
) -> None:
    await _log_in(client, telegram, "Socio A")
    assert (await client.get(STOCK)).status_code == 200
    assert (await client.get("/api/v1/sales")).status_code == 200

    rate = {"day": "2026-10-12", "rate": "876.80"}
    refused = await client.put("/api/v1/rates", json=rate)
    assert (refused.status_code, refused.json()) == (
        401,
        {"detail": "Falta la cabecera X-API-Key o no es válida."},
    )
    assert (await client.get("/api/v1/rates")).json()["total"] == 0

    assert (await client.put("/api/v1/rates", json=rate, headers=KEY)).status_code == 200


async def test_a_forged_cookie_reads_nothing(client: httpx.AsyncClient) -> None:
    client.cookies.set("fs_session", "forged")
    assert (await client.get(STOCK)).status_code == 401
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_without_telegram_the_code_is_logged_for_local_use(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        assert (await client.post("/api/auth/code", json={"name": "Socio A"})).status_code == 202
    match = re.search(r"login code for Socio A: (\d{6})", caplog.text)
    assert match, caplog.text
    login = await client.post("/api/auth/login", json={"name": "Socio A", "code": match[1]})
    assert login.status_code == 200


async def test_a_code_telegram_cannot_deliver_is_a_503_and_never_logged(
    client: httpx.AsyncClient, telegram: FakeTelegram, caplog: pytest.LogCaptureFixture
) -> None:
    telegram.failure = RuntimeError("Forbidden: bot can't initiate conversation with a user")
    with caplog.at_level(logging.WARNING):
        response = await client.post("/api/auth/code", json={"name": "Socio A"})
    assert response.status_code == 503
    assert "Telegram" in response.json()["detail"]
    assert re.search(r"\d{6}", caplog.text) is None

    telegram.failure = None
    assert (await client.post("/api/auth/code", json={"name": "Socio A"})).status_code == 202


async def test_a_configured_bot_that_did_not_start_is_a_503(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(settings, "telegram_bot_token", "token")
    monkeypatch.setattr(app.state, "telegram", None, raising=False)
    with caplog.at_level(logging.WARNING):
        response = await client.post("/api/auth/code", json={"name": "Socio A"})
    assert response.status_code == 503
    assert "login code" not in caplog.text


async def test_the_cookie_is_secure_over_https(clock: Clock, telegram: FakeTelegram) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
        login = await _log_in(client, telegram, "Dev")
    assert "Secure" in login.headers["set-cookie"]
