"""reset_db and restore_db, run against scratch databases on the test server."""

import asyncio
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from unittest.mock import patch

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from app import reset_db, restore_db
from tests.conftest import TEST_DATABASE_URL

SERVER = make_url(TEST_DATABASE_URL)
PRODUCTION_URL = "postgresql://francisco:secreto@prod.example.com:5432/railway"


def _url(name: str) -> str:
    return SERVER.set(database=name).render_as_string(hide_password=False)


async def _execute(name: str, *statements: str) -> None:
    connection = await asyncpg.connect(
        make_url(_url(name)).set(drivername="postgresql").render_as_string(hide_password=False)
    )
    try:
        for statement in statements:
            await connection.execute(statement)
    finally:
        await connection.close()


async def _tables(url: str) -> dict[str, list[tuple]]:
    connection = await asyncpg.connect(
        make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)
    )
    try:
        names = await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
        return {
            row["tablename"]: [
                tuple(record)
                for record in await connection.fetch(f'SELECT * FROM "{row["tablename"]}"')
            ]
            for row in names
        }
    finally:
        await connection.close()


@pytest.fixture
def scratch_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., str]]:
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    created: list[str] = []

    def create(*statements: str) -> str:
        name = f"francisco_scratch_{uuid.uuid4().hex[:12]}"
        asyncio.run(_execute("postgres", f'CREATE DATABASE "{name}"'))
        created.append(name)
        asyncio.run(_execute(name, *statements))
        return _url(name)

    yield create
    for name in created:
        asyncio.run(_execute("postgres", f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def _fails(main: Callable[[list[str]], None], *argv: str) -> str:
    with pytest.raises(SystemExit) as raised:
        main(list(argv))
    return str(raised.value.code)


class TestRestoreDb:
    def test_the_target_becomes_an_exact_copy_of_the_source(
        self, scratch_database, monkeypatch
    ) -> None:
        source = scratch_database(
            "CREATE TABLE partner (name text)", "INSERT INTO partner VALUES ('Daniel')"
        )
        target = scratch_database(
            "CREATE TABLE leftover (id int)", "INSERT INTO leftover VALUES (1)"
        )
        monkeypatch.setenv("PRODUCTION_DATABASE_URL", source)
        monkeypatch.setenv("DATABASE_URL", target)

        restore_db.main(["--from", "production", "--to", "local", "--yes"])

        assert asyncio.run(_tables(target)) == {"partner": [("Daniel",)]}

    def test_a_dump_that_fails_leaves_the_target_untouched(
        self, scratch_database, monkeypatch
    ) -> None:
        target = scratch_database(
            "CREATE TABLE leftover (id int)", "INSERT INTO leftover VALUES (1)"
        )
        monkeypatch.setenv("STAGING_DATABASE_URL", _url(f"missing_{uuid.uuid4().hex[:8]}"))
        monkeypatch.setenv("DATABASE_URL", target)

        message = _fails(restore_db.main, "--from", "staging", "--to", "local", "--yes")

        assert message.startswith("No se pudo sacar el dump de staging")
        assert asyncio.run(_tables(target)) == {"leftover": [(1,)]}

    def test_production_is_never_a_target(self, capsys) -> None:
        _fails(restore_db.main, "--from", "staging", "--to", "production", "--yes")

        assert "invalid choice: 'production'" in capsys.readouterr().err

    def test_a_target_whose_url_points_at_production_is_refused(self, monkeypatch) -> None:
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        monkeypatch.setenv("PRODUCTION_DATABASE_URL", PRODUCTION_URL)
        monkeypatch.setenv("STAGING_DATABASE_URL", PRODUCTION_URL.replace("secreto", "otra"))

        message = _fails(restore_db.main, "--from", "local", "--to", "staging", "--yes")

        assert message == "STAGING_DATABASE_URL apunta a la base de producción. No se toca."

    def test_the_same_database_as_source_and_target_is_refused(self) -> None:
        message = _fails(restore_db.main, "--from", "local", "--to", "local", "--yes")

        assert message == "El origen y el destino son la misma base."

    def test_a_missing_url_names_the_variable(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        monkeypatch.delenv("STAGING_DATABASE_URL", raising=False)

        message = _fails(restore_db.main, "--from", "local", "--to", "staging", "--yes")

        assert message.startswith("Falta STAGING_DATABASE_URL")

    def test_an_answer_other_than_the_target_name_cancels(
        self, scratch_database, monkeypatch
    ) -> None:
        source = scratch_database("CREATE TABLE partner (name text)")
        target = scratch_database("CREATE TABLE leftover (id int)")
        monkeypatch.setenv("STAGING_DATABASE_URL", source)
        monkeypatch.setenv("DATABASE_URL", target)

        with patch("builtins.input", return_value="si"):
            message = _fails(restore_db.main, "--from", "staging", "--to", "local")

        assert message == "Cancelado: no se tocó nada."
        assert asyncio.run(_tables(target)) == {"leftover": []}


class TestResetDb:
    def test_production_is_not_a_choice(self, capsys) -> None:
        _fails(reset_db.main, "production", "--yes")

        assert "invalid choice: 'production'" in capsys.readouterr().err

    def test_it_refuses_to_run_inside_railway(self, monkeypatch) -> None:
        monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")

        message = _fails(reset_db.main, "local", "--yes")

        assert message == "Esto corre solo desde un checkout local, nunca dentro de Railway."

    def test_a_local_url_that_points_at_production_is_refused(self, monkeypatch) -> None:
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
        monkeypatch.setenv("PRODUCTION_DATABASE_URL", PRODUCTION_URL)
        monkeypatch.setenv(
            "DATABASE_URL", PRODUCTION_URL.replace("postgresql://", "postgresql+asyncpg://")
        )

        message = _fails(reset_db.main, "local", "--yes")

        assert message == "DATABASE_URL apunta a la base de producción. No se toca."

    def test_it_leaves_only_the_migrated_schema(self, scratch_database, monkeypatch) -> None:
        target = scratch_database("CREATE TABLE leftover (id int)")
        monkeypatch.setenv("DATABASE_URL", target)

        reset_db.main(["local", "--yes"])

        tables = asyncio.run(_tables(target))
        assert "leftover" not in tables
        assert {"alembic_version", "partners", "purchases"} <= tables.keys()
