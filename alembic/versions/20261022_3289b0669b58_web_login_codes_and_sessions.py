"""web login codes and sessions: the OTP sent by Telegram and the browser cookie

Revision ID: 3289b0669b58
Revises: 9c4f1e6a2b58
Create Date: 2026-10-22 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3289b0669b58"
down_revision: str | Sequence[str] | None = "9c4f1e6a2b58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_codes",
        sa.Column("telegram_user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tries", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("telegram_user_id", name=op.f("pk_login_codes")),
    )
    op.create_table(
        "web_sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_web_sessions")),
    )
    op.create_index(
        op.f("ix_web_sessions_telegram_user_id"), "web_sessions", ["telegram_user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_web_sessions_telegram_user_id"), table_name="web_sessions")
    op.drop_table("web_sessions")
    op.drop_table("login_codes")
