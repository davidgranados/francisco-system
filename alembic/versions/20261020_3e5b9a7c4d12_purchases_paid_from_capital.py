"""purchases paid from capital, reinvestment at the settlement

Revision ID: 3e5b9a7c4d12
Revises: 7c1d4e8a2f60
Create Date: 2026-10-20 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3e5b9a7c4d12"
down_revision: str | Sequence[str] | None = "7c1d4e8a2f60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOTE = "'Compra ' || purchases.id || ' pagada por el socio, pasada a aporte'"


def upgrade() -> None:
    """Every purchase a partner paid becomes that partner's contribution to the capital."""
    op.add_column(
        "settlements",
        sa.Column("reinvest_usd", sa.Numeric(14, 2), server_default=sa.text("0"), nullable=False),
    )
    op.execute(
        "INSERT INTO contributions (partner_id, day, amount_usd, note) "
        f"SELECT paid_by_partner_id, day, total_usd, {NOTE} FROM purchases "
        "WHERE paid_by_partner_id IS NOT NULL AND NOT voided ORDER BY id"
    )
    op.drop_constraint(
        op.f("fk_purchases_paid_by_partner_id_partners"), "purchases", type_="foreignkey"
    )
    op.drop_column("purchases", "paid_by_partner_id")


def downgrade() -> None:
    """Give each converted purchase its partner back and delete the contributions made from it."""
    op.add_column("purchases", sa.Column("paid_by_partner_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_purchases_paid_by_partner_id_partners"),
        "purchases",
        "partners",
        ["paid_by_partner_id"],
        ["id"],
    )
    op.execute(
        "UPDATE purchases SET paid_by_partner_id = contributions.partner_id "
        f"FROM contributions WHERE contributions.note = {NOTE}"
    )
    op.execute(
        "DELETE FROM contributions USING purchases "
        f"WHERE contributions.note = {NOTE} AND purchases.paid_by_partner_id IS NOT NULL"
    )
    op.drop_column("settlements", "reinvest_usd")
