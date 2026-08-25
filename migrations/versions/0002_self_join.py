"""Вступление в клуб по общему коду

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "club_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Открытым текстом намеренно: это общий код приглашения, а не личный секрет —
        # администратор показывает его в клубном чате снова и снова.
        sa.Column("join_code", sa.String(length=32), nullable=False),
        sa.Column("join_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column(
        "members",
        sa.Column("self_joined", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("members", "self_joined")
    op.drop_table("club_settings")
