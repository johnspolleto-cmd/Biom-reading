"""Начальная схема «ЧитКода»

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "levels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("idx", sa.Integer(), nullable=False, unique=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("threshold_pages", sa.Integer(), nullable=False),
        sa.Column("avatar_file", sa.String(length=120), nullable=False),
        sa.Column("color", sa.String(length=20), nullable=False, server_default="#6b7280"),
    )

    op.create_table(
        "members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("full_name", sa.String(length=160), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="member"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("token_prefix", sa.String(length=12), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("pin_hash", sa.String(length=255)),
        sa.Column("pin_set_at", sa.DateTime(timezone=True)),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("auth_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("joined_at", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_members_token_prefix", "members", ["token_prefix"])

    op.create_table(
        "books",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("member_id", sa.Integer(),
                  sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("total_pages", sa.Integer()),
        sa.Column("format", sa.String(length=16), nullable=False, server_default="paper"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="reading"),
        sa.Column("started_at", sa.Date()),
        sa.Column("finished_at", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status in ('reading','finished')", name="ck_books_status"),
        sa.CheckConstraint("format in ('paper','ebook')", name="ck_books_format"),
    )
    op.create_index("ix_books_member_id", "books", ["member_id"])
    op.create_index("ix_books_member_status", "books", ["member_id", "status"])

    op.create_table(
        "reading_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("member_id", sa.Integer(),
                  sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id", ondelete="SET NULL")),
        sa.Column("pages", sa.Integer(), nullable=False),
        sa.Column("input_kind", sa.String(length=16), nullable=False, server_default="pages"),
        sa.Column("input_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("note", sa.String(length=500)),
        sa.Column("is_flagged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("flag_reason", sa.String(length=200)),
        sa.Column("moderated_by", sa.Integer(), sa.ForeignKey("members.id")),
        sa.Column("moderated_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("pages > 0", name="ck_entries_pages_positive"),
        sa.CheckConstraint("input_kind in ('pages','percent')", name="ck_entries_input_kind"),
    )
    op.create_index("ix_reading_entries_member_id", "reading_entries", ["member_id"])
    op.create_index("ix_reading_entries_entry_date", "reading_entries", ["entry_date"])
    op.create_index("ix_entries_member_date", "reading_entries", ["member_id", "entry_date"])

    op.create_table(
        "quotes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("member_id", sa.Integer(),
                  sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id", ondelete="SET NULL")),
        sa.Column("book_label", sa.String(length=400), nullable=False, server_default=""),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_quotes_member_id", "quotes", ["member_id"])

    op.create_table(
        "challenges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("week_start", sa.Date(), nullable=False, unique=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("type", sa.String(length=24), nullable=False),
        sa.Column("target_value", sa.Integer()),
        sa.Column("genre", sa.String(length=80)),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "type in ('pages_total','finish_book','days_streak','genre')",
            name="ck_challenges_type",
        ),
    )

    op.create_table(
        "challenge_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("challenge_id", sa.Integer(),
                  sa.ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False),
        sa.Column("member_id", sa.Integer(),
                  sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("progress_value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confirmed_by", sa.Integer(), sa.ForeignKey("members.id")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("challenge_id", "member_id", name="uq_result_challenge_member"),
        sa.CheckConstraint(
            "status in ('pending','claimed','completed','rejected')", name="ck_results_status"
        ),
    )

    op.create_table(
        "club_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id", ondelete="CASCADE")),
        # JSONB на PostgreSQL, обычный JSON на SQLite — как в моделях
        sa.Column("payload", sa.JSON().with_variant(postgresql.JSONB, "postgresql"),
                  nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_club_events_created_at", "club_events", ["created_at"])

    # Стартовые уровни. Названия потом правятся прямо в базе, без деплоя.
    op.bulk_insert(
        sa.table(
            "levels",
            sa.column("idx", sa.Integer),
            sa.column("name", sa.String),
            sa.column("threshold_pages", sa.Integer),
            sa.column("avatar_file", sa.String),
            sa.column("color", sa.String),
        ),
        [
            {"idx": 0, "name": "Новичок", "threshold_pages": 0,
             "avatar_file": "level0.svg", "color": "#94a3b8"},
            {"idx": 1, "name": "Младенец", "threshold_pages": 100,
             "avatar_file": "level1.svg", "color": "#f9a8d4"},
            {"idx": 2, "name": "Первые шаги", "threshold_pages": 500,
             "avatar_file": "level2.svg", "color": "#7dd3fc"},
            {"idx": 3, "name": "Жёлтый рейнджер", "threshold_pages": 1000,
             "avatar_file": "level3.svg", "color": "#facc15"},
            {"idx": 4, "name": "Колобок", "threshold_pages": 2000,
             "avatar_file": "level4.svg", "color": "#fb923c"},
            {"idx": 5, "name": "Паучок", "threshold_pages": 5000,
             "avatar_file": "level5.svg", "color": "#a78bfa"},
            {"idx": 6, "name": "Хранитель Биома", "threshold_pages": 10000,
             "avatar_file": "level6.svg", "color": "#34d399"},
        ],
    )


def downgrade() -> None:
    op.drop_table("club_events")
    op.drop_table("challenge_results")
    op.drop_table("challenges")
    op.drop_table("quotes")
    op.drop_table("reading_entries")
    op.drop_table("books")
    op.drop_table("members")
    op.drop_table("levels")
