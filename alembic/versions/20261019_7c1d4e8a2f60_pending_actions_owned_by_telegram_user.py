"""pending actions owned by the telegram user

Revision ID: 7c1d4e8a2f60
Revises: ea27d2008e0e
Create Date: 2026-10-19 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c1d4e8a2f60"
down_revision: str | Sequence[str] | None = "ea27d2008e0e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Own each pending action by the Telegram user id, copied from its partner.

    Rows whose partner has no Telegram id cannot be pressed by anyone, so they are deleted.
    """
    op.add_column("pending_actions", sa.Column("telegram_user_id", sa.BigInteger(), nullable=True))
    op.execute(
        "UPDATE pending_actions SET telegram_user_id = partners.telegram_user_id "
        "FROM partners WHERE partners.id = pending_actions.partner_id"
    )
    op.execute("DELETE FROM pending_actions WHERE telegram_user_id IS NULL")
    op.alter_column("pending_actions", "telegram_user_id", nullable=False)
    op.drop_constraint(
        op.f("fk_pending_actions_partner_id_partners"), "pending_actions", type_="foreignkey"
    )
    op.drop_column("pending_actions", "partner_id")


def downgrade() -> None:
    """Own each pending action by a partner again; a non-partner's rows are deleted."""
    op.add_column("pending_actions", sa.Column("partner_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE pending_actions SET partner_id = partners.id "
        "FROM partners WHERE partners.telegram_user_id = pending_actions.telegram_user_id"
    )
    op.execute("DELETE FROM pending_actions WHERE partner_id IS NULL")
    op.alter_column("pending_actions", "partner_id", nullable=False)
    op.create_foreign_key(
        op.f("fk_pending_actions_partner_id_partners"),
        "pending_actions",
        "partners",
        ["partner_id"],
        ["id"],
    )
    op.drop_column("pending_actions", "telegram_user_id")
