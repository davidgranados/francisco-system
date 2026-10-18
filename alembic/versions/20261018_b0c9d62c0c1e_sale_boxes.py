"""sale boxes

Revision ID: b0c9d62c0c1e
Revises: f46a0d588d2e
Create Date: 2026-10-18 18:13:55.847658

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b0c9d62c0c1e"
down_revision: str | Sequence[str] | None = "f46a0d588d2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_QUANTITIES = "cartons >= 0 AND halves >= 0 AND units >= 0 AND cartons + halves + units > 0"
NEW_QUANTITIES = (
    "boxes >= 0 AND cartons >= 0 AND halves >= 0 AND units >= 0 "
    "AND boxes + cartons + halves + units > 0"
)


def upgrade() -> None:
    op.add_column(
        "sales", sa.Column("boxes", sa.Integer(), server_default=sa.text("0"), nullable=False)
    )
    op.drop_constraint(op.f("ck_sales_quantities"), "sales", type_="check")
    op.create_check_constraint(op.f("ck_sales_quantities"), "sales", NEW_QUANTITIES)


def downgrade() -> None:
    op.drop_constraint(op.f("ck_sales_quantities"), "sales", type_="check")
    op.create_check_constraint(op.f("ck_sales_quantities"), "sales", OLD_QUANTITIES)
    op.drop_column("sales", "boxes")
