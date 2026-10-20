"""expenses remember whether their cierre paid the partner back

Revision ID: 5a8e2d0b7f31
Revises: 3e5b9a7c4d12
Create Date: 2026-10-21 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5a8e2d0b7f31"
down_revision: str | Sequence[str] | None = "3e5b9a7c4d12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """A partner expense given back on its cierre's day is taken as paid by that cierre."""
    op.add_column(
        "expenses",
        sa.Column(
            "reimbursed_by_settlement",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE expenses SET reimbursed_by_settlement = true FROM settlements "
        "WHERE expenses.settlement_id = settlements.id "
        "AND expenses.paid_by_partner_id IS NOT NULL "
        "AND expenses.reimbursed_on = settlements.day"
    )
    op.create_check_constraint(
        op.f("ck_expenses_reimbursed_by_settlement"),
        "expenses",
        "NOT reimbursed_by_settlement OR (settlement_id IS NOT NULL "
        "AND reimbursed_on IS NOT NULL AND paid_by_partner_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_expenses_reimbursed_by_settlement"), "expenses", type_="check")
    op.drop_column("expenses", "reimbursed_by_settlement")
