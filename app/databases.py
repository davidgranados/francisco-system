"""The databases a developer can reset or copy from a local checkout, and the steps that do it."""

import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import asyncpg
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parent.parent


class Database(StrEnum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


WRITABLE = (Database.LOCAL, Database.STAGING)
URL_VARIABLES = {
    Database.LOCAL: "DATABASE_URL",
    Database.STAGING: "STAGING_DATABASE_URL",
    Database.PRODUCTION: "PRODUCTION_DATABASE_URL",
}


class Urls(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = ""
    staging_database_url: str = ""
    production_database_url: str = ""
    pg_tools: str = "docker compose exec -T postgres"

    def of(self, database: Database) -> str:
        return getattr(self, URL_VARIABLES[database].lower())


class DatabaseError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Target:
    database: Database
    url: str

    @property
    def server(self) -> tuple[str | None, int | None, str | None]:
        url = make_url(self.url)
        return (url.host, url.port or 5432, url.database)

    @property
    def libpq_url(self) -> str:
        """The URL without SQLAlchemy's driver suffix, the form pg_dump and asyncpg read."""
        return make_url(self.url).set(drivername="postgresql").render_as_string(hide_password=False)

    def __str__(self) -> str:
        host, port, name = self.server
        return f"{self.database} ({name} en {host}:{port})"


def resolve(database: Database, urls: Urls) -> Target:
    url = urls.of(database)
    if not url:
        raise DatabaseError(f"Falta {URL_VARIABLES[database]}: es la URL de la base {database}.")
    return Target(database, url)


def writable(database: Database, urls: Urls) -> Target:
    """Resolve a database this checkout may overwrite, refusing production however it is reached."""
    if os.environ.get("RAILWAY_ENVIRONMENT_NAME"):
        raise DatabaseError("Esto corre solo desde un checkout local, nunca dentro de Railway.")
    if database not in WRITABLE:
        raise DatabaseError(f"La base {database} nunca se sobrescribe.")
    target = resolve(database, urls)
    production = urls.of(Database.PRODUCTION)
    if production and Target(Database.PRODUCTION, production).server == target.server:
        raise DatabaseError(
            f"{URL_VARIABLES[database]} apunta a la base de producción. No se toca."
        )
    return target


def confirm(target: Target, action: str) -> None:
    if input(f"{action}. Escriba {target.database} para seguir: ") != target.database:
        raise DatabaseError("Cancelado: no se tocó nada.")


async def drop_public_schema(target: Target, recreate: bool) -> None:
    """Drop the public schema with everything in it; a dump of it brings it back on restore."""
    connection = await asyncpg.connect(target.libpq_url)
    try:
        await connection.execute("DROP SCHEMA IF EXISTS public CASCADE")
        if recreate:
            await connection.execute("CREATE SCHEMA public")
    finally:
        await connection.close()


def dump(source: Target, path: Path, urls: Urls) -> None:
    with path.open("wb") as output:
        _run(
            [
                *shlex.split(urls.pg_tools),
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--schema=public",
                source.libpq_url,
            ],
            f"No se pudo sacar el dump de {source}",
            stdout=output,
        )


def restore(path: Path, target: Target, urls: Urls) -> None:
    with path.open("rb") as dump_file:
        _run(
            [
                *shlex.split(urls.pg_tools),
                "pg_restore",
                "--no-owner",
                "--no-privileges",
                "--single-transaction",
                f"--dbname={target.libpq_url}",
            ],
            f"No se pudo restaurar el dump en {target}",
            stdin=dump_file,
        )


def migrate(target: Target) -> None:
    _run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        f"Las migraciones fallaron en {target}",
        environment={"DATABASE_URL": target.url},
    )


def _run(command: list[str], failure: str, environment: dict[str, str] | None = None, **streams):
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env={**os.environ, **(environment or {})},
            stderr=subprocess.PIPE,
            check=False,
            **streams,
        )
    except FileNotFoundError as error:
        raise DatabaseError(f"{failure}: no se encontró {command[0]}.") from error
    if completed.returncode != 0:
        raise DatabaseError(f"{failure}:\n{completed.stderr.decode(errors='replace').strip()}")
