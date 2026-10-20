"""fund transfers: money between funds and out to a partner

Revision ID: 9c4f1e6a2b58
Revises: 5a8e2d0b7f31
Create Date: 2026-10-21 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c4f1e6a2b58"
down_revision: str | Sequence[str] | None = "5a8e2d0b7f31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNDS = ("capital", "petty_cash", "savings")
KINDS = ("between_funds", "contribution_return", "profit_withdrawal")


def _fund() -> sa.Enum:
    return sa.Enum(*FUNDS, name="fund", native_enum=False, length=20)


def upgrade() -> None:
    op.create_table(
        "fund_transfers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(*KINDS, name="transferkind", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("from_fund", _fund(), nullable=False),
        sa.Column("to_fund", _fund(), nullable=True),
        sa.Column("partner_id", sa.Integer(), nullable=True),
        sa.Column("amount_usd", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("voided", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount_usd > 0", name=op.f("ck_fund_transfers_amount_positive")),
        sa.CheckConstraint(
            "(kind = 'between_funds' AND to_fund IS NOT NULL AND to_fund <> from_fund "
            "AND partner_id IS NULL) "
            "OR (kind = 'contribution_return' AND from_fund = 'capital' AND to_fund IS NULL "
            "AND partner_id IS NOT NULL) "
            "OR (kind = 'profit_withdrawal' AND to_fund IS NULL AND partner_id IS NOT NULL)",
            name=op.f("ck_fund_transfers_shape"),
        ),
        sa.CheckConstraint(
            "from_fund IN ('capital', 'petty_cash', 'savings') AND "
            "(to_fund IS NULL OR to_fund IN ('capital', 'petty_cash', 'savings'))",
            name=op.f("ck_fund_transfers_funds"),
        ),
        sa.ForeignKeyConstraint(
            ["partner_id"], ["partners.id"], name=op.f("fk_fund_transfers_partner_id_partners")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fund_transfers")),
    )
    op.create_index(op.f("ix_fund_transfers_day"), "fund_transfers", ["day"], unique=False)
    op.create_index(
        op.f("ix_fund_transfers_partner_id"), "fund_transfers", ["partner_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_fund_transfers_partner_id"), table_name="fund_transfers")
    op.drop_index(op.f("ix_fund_transfers_day"), table_name="fund_transfers")
    op.drop_table("fund_transfers")
