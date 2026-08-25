"""Модели данных.

Принцип: суммарные и недельные показатели НИГДЕ не хранятся полем — они всегда
считаются агрегацией из reading_entries (см. app/domain/leaderboard.py).
Рассинхронизироваться нечему.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import db

# JSONB на PostgreSQL, обычный JSON на SQLite (тесты гоняются без сервера БД)
JsonType = sa.JSON().with_variant(JSONB, "postgresql")


def utcnow() -> datetime:
    """Текущее время в UTC. Всё в базе хранится в UTC, показывается по Москве."""
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Level(db.Model):
    """Уровни читателя. Таблица, а не константа: название можно поменять без деплоя."""

    __tablename__ = "levels"

    id: Mapped[int] = mapped_column(primary_key=True)
    idx: Mapped[int] = mapped_column(sa.Integer, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    threshold_pages: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    avatar_file: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    color: Mapped[str] = mapped_column(sa.String(20), nullable=False, default="#6b7280")

    def to_dict(self) -> dict[str, Any]:
        return {
            "idx": self.idx,
            "name": self.name,
            "threshold_pages": self.threshold_pages,
            "avatar": f"/static/levels/{self.avatar_file}",
            "color": self.color,
        }


class ClubSettings(TimestampMixin, db.Model):
    """Настройки клуба. Всегда ровно одна строка (id = 1).

    join_code хранится открытым текстом намеренно: это не персональный секрет,
    а общий код приглашения, который админ показывает в клубном чате снова и снова.
    """

    __tablename__ = "club_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    join_code: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    join_enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)


class Member(TimestampMixin, db.Model):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    role: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="member")
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)

    # Доступ: персональная ссылка с токеном + четырёхзначный PIN.
    # Токен хранится хешем; prefix — только чтобы найти строку по индексу.
    token_prefix: Mapped[str] = mapped_column(sa.String(12), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    pin_hash: Mapped[Optional[str]] = mapped_column(sa.String(255), nullable=True)
    pin_set_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))
    failed_attempts: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))
    # Увеличение auth_version мгновенно отзывает все выданные cookie участника
    auth_version: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)

    joined_at: Mapped[date] = mapped_column(sa.Date, nullable=False, default=date.today)
    # Записался сам по коду клуба, а не заведён администратором
    self_joined: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)

    books: Mapped[list["Book"]] = relationship(back_populates="member", cascade="all, delete-orphan")
    # foreign_keys обязателен: у reading_entries два ключа на members —
    # автор записи и админ, который её проверил
    entries: Mapped[list["ReadingEntry"]] = relationship(
        back_populates="member",
        cascade="all, delete-orphan",
        foreign_keys="ReadingEntry.member_id",
    )
    quotes: Mapped[list["Quote"]] = relationship(
        back_populates="member", cascade="all, delete-orphan"
    )

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def pin_is_set(self) -> bool:
        return self.pin_hash is not None


class Book(TimestampMixin, db.Model):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(
        sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author: Mapped[str] = mapped_column(sa.String(160), nullable=False, default="")
    title: Mapped[str] = mapped_column(sa.String(240), nullable=False)
    total_pages: Mapped[Optional[int]] = mapped_column(sa.Integer)
    fmt: Mapped[str] = mapped_column("format", sa.String(16), nullable=False, default="paper")
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="reading")
    started_at: Mapped[Optional[date]] = mapped_column(sa.Date)
    finished_at: Mapped[Optional[date]] = mapped_column(sa.Date)

    member: Mapped[Member] = relationship(back_populates="books")

    __table_args__ = (
        sa.CheckConstraint("status in ('reading','finished')", name="ck_books_status"),
        sa.CheckConstraint("format in ('paper','ebook')", name="ck_books_format"),
        sa.Index("ix_books_member_status", "member_id", "status"),
    )

    @property
    def label(self) -> str:
        """Подпись книги с кавычками-«ёлочками»: Автор — «Название»."""
        return f"{self.author} — «{self.title}»" if self.author else f"«{self.title}»"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "member_id": self.member_id,
            "author": self.author,
            "title": self.title,
            "total_pages": self.total_pages,
            "format": self.fmt,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class ReadingEntry(TimestampMixin, db.Model):
    """Событие журнала: «+37 страниц такого-то числа». Никогда не переписывает итог."""

    __tablename__ = "reading_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(
        sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False, index=True
    )
    book_id: Mapped[Optional[int]] = mapped_column(sa.ForeignKey("books.id", ondelete="SET NULL"))

    pages: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    # Что участник ввёл на самом деле: страницы или проценты электронной книги.
    # Храним оба, чтобы пересчитать, если объём книги уточнят позже.
    input_kind: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="pages")
    input_value: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0)

    entry_date: Mapped[date] = mapped_column(sa.Date, nullable=False, index=True)
    note: Mapped[Optional[str]] = mapped_column(sa.String(500))

    is_flagged: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    flag_reason: Mapped[Optional[str]] = mapped_column(sa.String(200))
    moderated_by: Mapped[Optional[int]] = mapped_column(sa.ForeignKey("members.id"))
    moderated_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))

    # Мягкое удаление: строка уходит из подсчётов, но история клуба не теряется
    deleted_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))

    member: Mapped[Member] = relationship(back_populates="entries", foreign_keys=[member_id])
    book: Mapped[Optional[Book]] = relationship()

    __table_args__ = (
        sa.CheckConstraint("pages > 0", name="ck_entries_pages_positive"),
        sa.CheckConstraint("input_kind in ('pages','percent')", name="ck_entries_input_kind"),
        sa.Index("ix_entries_member_date", "member_id", "entry_date"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "member_id": self.member_id,
            "book_id": self.book_id,
            "book": self.book.label if self.book else None,
            "pages": self.pages,
            "input_kind": self.input_kind,
            "input_value": self.input_value,
            "entry_date": self.entry_date.isoformat(),
            "note": self.note,
            "is_flagged": self.is_flagged,
            "flag_reason": self.flag_reason,
            "created_at": self.created_at.isoformat(),
        }


class Quote(TimestampMixin, db.Model):
    __tablename__ = "quotes"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(
        sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False, index=True
    )
    book_id: Mapped[Optional[int]] = mapped_column(sa.ForeignKey("books.id", ondelete="SET NULL"))
    # Подпись книги остаётся, даже если книгу удалили
    book_label: Mapped[str] = mapped_column(sa.String(400), nullable=False, default="")
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    page: Mapped[Optional[int]] = mapped_column(sa.Integer)

    member: Mapped[Member] = relationship(back_populates="quotes")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "member_id": self.member_id,
            "member_name": self.member.full_name if self.member else None,
            "book_id": self.book_id,
            "book": self.book_label,
            "text": self.text,
            "page": self.page,
            "created_at": self.created_at.isoformat(),
        }


class Challenge(TimestampMixin, db.Model):
    """Челлендж недели. Текущий выбирается запросом по week_start, а не публикуется кроном."""

    __tablename__ = "challenges"

    id: Mapped[int] = mapped_column(primary_key=True)
    week_start: Mapped[date] = mapped_column(sa.Date, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    kind: Mapped[str] = mapped_column("type", sa.String(24), nullable=False)
    target_value: Mapped[Optional[int]] = mapped_column(sa.Integer)
    genre: Mapped[Optional[str]] = mapped_column(sa.String(80))
    is_published: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)

    results: Mapped[list["ChallengeResult"]] = relationship(
        back_populates="challenge", cascade="all, delete-orphan"
    )

    __table_args__ = (
        sa.CheckConstraint(
            "type in ('pages_total','finish_book','days_streak','genre')",
            name="ck_challenges_type",
        ),
    )

    @property
    def is_auto(self) -> bool:
        """Числовые челленджи засчитываются сами; «мягкие» отмечает участник."""
        return self.kind in {"pages_total", "finish_book", "days_streak"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "week_start": self.week_start.isoformat(),
            "title": self.title,
            "description": self.description,
            "type": self.kind,
            "target_value": self.target_value,
            "genre": self.genre,
            "is_auto": self.is_auto,
            "is_published": self.is_published,
        }


class ChallengeResult(TimestampMixin, db.Model):
    __tablename__ = "challenge_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    challenge_id: Mapped[int] = mapped_column(
        sa.ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False
    )
    member_id: Mapped[int] = mapped_column(
        sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    # pending — в процессе, claimed — участник отметил сам, ждёт админа,
    # completed — засчитано, rejected — админ отклонил
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="pending")
    progress_value: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    confirmed_by: Mapped[Optional[int]] = mapped_column(sa.ForeignKey("members.id"))
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))

    challenge: Mapped[Challenge] = relationship(back_populates="results")
    member: Mapped[Member] = relationship(foreign_keys=[member_id])

    __table_args__ = (
        sa.UniqueConstraint("challenge_id", "member_id", name="uq_result_challenge_member"),
        sa.CheckConstraint(
            "status in ('pending','claimed','completed','rejected')", name="ck_results_status"
        ),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "challenge_id": self.challenge_id,
            "member_id": self.member_id,
            "member_name": self.member.full_name if self.member else None,
            "status": self.status,
            "progress_value": self.progress_value,
        }


class ClubEvent(db.Model):
    """Общая лента клуба: переходы на уровень, дочитанные книги, победы в челлендже."""

    __tablename__ = "club_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column("type", sa.String(32), nullable=False)
    member_id: Mapped[Optional[int]] = mapped_column(sa.ForeignKey("members.id", ondelete="CASCADE"))
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    member: Mapped[Optional[Member]] = relationship()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.kind,
            "member_id": self.member_id,
            "member_name": self.member.full_name if self.member else None,
            "payload": self.payload or {},
            "created_at": self.created_at.isoformat(),
        }
