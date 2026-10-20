"""Empty the local or staging database and migrate it: python -m app.reset_db local

Production is not a choice. The migrations are this checkout's, so reset staging from main.
"""

import argparse
import asyncio

from app import databases
from app.databases import Database, DatabaseError


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.reset_db", description=__doc__)
    parser.add_argument("database", choices=[database.value for database in databases.WRITABLE])
    parser.add_argument("--yes", action="store_true", help="no preguntar antes de borrar")
    options = parser.parse_args(argv)
    try:
        target = databases.writable(Database(options.database), databases.Urls())
        if target.database == Database.STAGING:
            print("Las migraciones salen de este checkout: para staging, que esté en main.")
        if not options.yes:
            databases.confirm(target, f"Se borra todo en {target}")
        asyncio.run(databases.drop_public_schema(target, recreate=True))
        print(f"{target} quedó vacía. Aplicando migraciones...")
        databases.migrate(target)
    except DatabaseError as error:
        raise SystemExit(error.message) from error
    print(f"{target} quedó reiniciada.")


if __name__ == "__main__":
    main()
