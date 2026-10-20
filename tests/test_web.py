from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from app.main import create_app

INDEX = "<!doctype html><title>Cuentas</title>"


@pytest.fixture
async def web(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "app.js").write_text("console.log('cuentas')")
    (dist / "favicon.svg").write_text("<svg/>")
    (dist / "index.html").write_text(INDEX)
    (tmp_path / "secret.txt").write_text("secreto")
    transport = httpx.ASGITransport(app=create_app(dist))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.parametrize("path", ["/", "/ventas", "/cajas/3/hoja"])
async def test_client_routes_get_the_index(web: httpx.AsyncClient, path: str) -> None:
    response = await web.get(path)
    assert (response.status_code, response.text) == (200, INDEX)


async def test_built_files_are_served_as_they_are(web: httpx.AsyncClient) -> None:
    assert (await web.get("/assets/app.js")).text == "console.log('cuentas')"
    assert (await web.get("/favicon.svg")).text == "<svg/>"
    assert (await web.get("/assets/missing.js")).status_code == 404


@pytest.mark.parametrize("path", ["/api/v1/x", "/api/auth/x", "/telegram/x", "/docs/x"])
async def test_api_paths_never_fall_back_to_the_index(web: httpx.AsyncClient, path: str) -> None:
    response = await web.get(path)
    assert response.text != INDEX
    assert response.status_code in (401, 404)


async def test_a_file_outside_the_build_is_never_served(web: httpx.AsyncClient) -> None:
    response = await web.get("/..%2Fsecret.txt")
    assert (response.status_code, response.text) == (200, INDEX)


async def test_the_api_still_answers_beside_the_spa(web: httpx.AsyncClient) -> None:
    assert (await web.get("/api/v1/inventory/stock")).status_code == 401
    assert (await web.get("/openapi.json")).json()["info"]["title"] == "Francisco System"


async def test_without_a_build_nothing_is_served(tmp_path: Path) -> None:
    transport = httpx.ASGITransport(app=create_app(tmp_path / "missing"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/ventas")).status_code == 404
