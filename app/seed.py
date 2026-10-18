"""Set the partners: python -m app.seed "Nombre:0.60:telegram_id" "Otro:0.40" ...

The arguments are the complete set of active partners. Running it again with the same
arguments leaves the database as it was.
"""

import asyncio
import sys
from decimal import Decimal, InvalidOperation

from app.db import SessionLocal, engine
from app.domain.errors import DomainError
from app.services.partners import PartnerEntry, PartnerView, replace_partners


def parse_entry(raw: str) -> PartnerEntry:
    name, _, rest = raw.partition(":")
    share, _, telegram = rest.partition(":")
    try:
        return PartnerEntry(
            name=name.strip(),
            share=Decimal(share),
            telegram_user_id=int(telegram) if telegram.strip() else None,
        )
    except (InvalidOperation, ValueError) as error:
        raise SystemExit(f"Socio inválido «{raw}»: use Nombre:0.60:telegram_id") from error


async def seed(entries: list[PartnerEntry]) -> list[PartnerView]:
    try:
        async with SessionLocal() as session, session.begin():
            return await replace_partners(session, entries)
    finally:
        await engine.dispose()


def main(argv: list[str]) -> None:
    if not argv:
        raise SystemExit(__doc__)
    try:
        partners = asyncio.run(seed([parse_entry(raw) for raw in argv]))
    except DomainError as error:
        raise SystemExit(error.message) from error
    for partner in partners:
        print(f"{partner.name}: {partner.share * 100:.2f} % · telegram {partner.telegram_user_id}")


if __name__ == "__main__":
    main(sys.argv[1:])
