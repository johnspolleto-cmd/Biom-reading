"""Цвета уровней под тёмную тему

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# На тёмном фоне пастельные цвета светлой темы выцветают, поэтому свой набор.
DARK_COLORS = {
    0: "#6b7684",
    1: "#e39ac0",
    2: "#6fc7ee",
    3: "#e8c547",
    4: "#e08a4a",
    5: "#a98cf0",
    6: "#45d6a2",
}


def upgrade() -> None:
    op.add_column(
        "levels",
        sa.Column("color_dark", sa.String(length=20), nullable=False, server_default="#9ca3af"),
    )
    # Заполняем уже существующие уровни — на работающей установке они давно созданы
    levels = sa.table("levels", sa.column("idx", sa.Integer), sa.column("color_dark", sa.String))
    for idx, color in DARK_COLORS.items():
        op.execute(levels.update().where(levels.c.idx == idx).values(color_dark=color))


def downgrade() -> None:
    op.drop_column("levels", "color_dark")
