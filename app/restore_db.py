"""Copy one database over another: python -m app.restore_db --from production --to local

The target ends up identical to the source. Production can be a source, never a target.
"""

import argparse
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from app import databases
from app.databases import Database, DatabaseError


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.restore_db", description=__doc__)
    parser.add_argument("--from", dest="source", required=True, choices=list(Database))
    parser.add_argument("--to", dest="target", required=True, choices=list(databases.WRITABLE))
    parser.add_argument("--yes", action="store_true", help="no preguntar antes de reemplazar")
    options = parser.parse_args(argv)
    urls = databases.Urls()
    try:
        if options.source == options.target:
            raise DatabaseError("El origen y el destino son la misma base.")
        target = databases.writable(Database(options.target), urls)
        source = databases.resolve(Database(options.source), urls)
        if source.server == target.server:
            raise DatabaseError(f"{source} y {target} son la misma base.")
        if not options.yes:
            databases.confirm(target, f"Se reemplaza todo {target} por una copia de {source}")
        with TemporaryDirectory() as directory:
            path = Path(directory) / f"{source.database}.dump"
            print(f"Sacando el dump de {source}...")
            databases.dump(source, path, urls)
            print(f"Restaurando en {target}...")
            asyncio.run(databases.drop_public_schema(target, recreate=False))
            databases.restore(path, target, urls)
    except DatabaseError as error:
        raise SystemExit(error.message) from error
    print(f"{target} es ahora una copia de {source}.")
    if target.database == Database.LOCAL:
        print("Si este checkout trae migraciones nuevas, corra uv run alembic upgrade head.")


if __name__ == "__main__":
    main()
