"""Журнал чтения: добавление, правка, удаление записей.

Логика всегда «добавить порцию», никогда «переписать итог».
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from flask import current_app

from ..models import Book, Member, ReadingEntry, utcnow
from . import events
from .errors import DomainError, Forbidden, NotFound
from .leaderboard import total_pages_of
from .levels import level_for, load_levels
from .time_utils import as_utc, msk_today


def _resolve_book(session, member: Member, book_id: Optional[int]) -> Optional[Book]:
    if book_id is None:
        return None
    book = session.get(Book, book_id)
    if book is None:
        raise NotFound("Книга не найдена")
    if book.member_id != member.id:
        raise Forbidden("Это книга другого участника")
    return book


def _pages_from_percent(percent: float, book: Optional[Book]) -> int:
    if book is None:
        raise DomainError(
            "Чтобы вносить проценты, сначала укажите книгу — из её объёма считаются страницы",
            code="percent_without_book",
        )
    if percent <= 0:
        raise DomainError("Процент должен быть больше нуля", code="percent_not_positive")
    if percent > 100:
        raise DomainError("Больше 100 % книги прочитать нельзя", code="percent_too_big")
    volume = book.total_pages or current_app.config["DEFAULT_BOOK_PAGES"]
    return max(1, int(round(percent * volume / 100)))


def _validate_date(entry_date: Optional[date]) -> date:
    today = msk_today()
    if entry_date is None:
        return today
    if entry_date > today:
        raise DomainError("Дата чтения не может быть в будущем", code="future_date")
    max_back = current_app.config["ENTRY_MAX_BACKDATE_DAYS"]
    if entry_date < today - timedelta(days=max_back):
        raise DomainError(
            f"Задним числом можно вносить не больше чем за {max_back} дней",
            code="too_old_date",
        )
    return entry_date


def _flag_for(pages: int) -> tuple[bool, Optional[str]]:
    soft_max = current_app.config["ENTRY_PAGES_SOFT_MAX"]
    if pages > soft_max:
        return True, f"Больше {soft_max} страниц за одну запись — нужна проверка администратора"
    return False, None


def _level_change(session, member_id: int, before: int, after: int) -> Optional[dict[str, Any]]:
    """Если суммарные страницы перешагнули порог — вернуть данные нового уровня."""
    levels = load_levels(session)
    old = level_for(before, levels)
    new = level_for(after, levels)
    if new.idx <= old.idx:
        return None
    payload = {"level_idx": new.idx, "level_name": new.name, "total_pages": after,
               "avatar": new.avatar, "color": new.color}
    events.record(session, "level_up", member_id, payload)
    return payload


def add_entry(
    session,
    member: Member,
    *,
    pages: Optional[int] = None,
    percent: Optional[float] = None,
    book_id: Optional[int] = None,
    note: Optional[str] = None,
    entry_date: Optional[date] = None,
) -> dict[str, Any]:
    """Добавить порцию прочитанного. Возвращает запись и, если случился, переход на уровень."""
    if (pages is None) == (percent is None):
        raise DomainError("Укажите либо страницы, либо процент книги", code="input_ambiguous")

    book = _resolve_book(session, member, book_id)

    if percent is not None:
        input_kind, input_value = "percent", float(percent)
        pages_value = _pages_from_percent(float(percent), book)
    else:
        pages_value = int(pages)
        input_kind, input_value = "pages", float(pages_value)
        if pages_value < 1:
            raise DomainError("Страниц должно быть хотя бы одна", code="pages_not_positive")

    hard_max = current_app.config["ENTRY_PAGES_HARD_MAX"]
    if pages_value > hard_max:
        raise DomainError(
            f"Больше {hard_max} страниц за одну запись — это наверняка опечатка. "
            "Разбейте на несколько записей.",
            code="pages_too_big",
        )

    flagged, reason = _flag_for(pages_value)
    before = total_pages_of(session, member.id)

    entry = ReadingEntry(
        member_id=member.id,
        book_id=book.id if book else None,
        pages=pages_value,
        input_kind=input_kind,
        input_value=input_value,
        entry_date=_validate_date(entry_date),
        note=(note or "").strip() or None,
        is_flagged=flagged,
        flag_reason=reason,
    )
    session.add(entry)
    session.flush()

    level_up = _level_change(session, member.id, before, before + pages_value)
    return {"entry": entry, "level_up": level_up}


def _assert_can_edit(entry: ReadingEntry, actor: Member) -> None:
    if actor.is_admin:
        return
    if entry.member_id != actor.id:
        raise Forbidden("Редактировать можно только свои записи")
    window = current_app.config["ENTRY_EDIT_WINDOW"]
    if utcnow() - as_utc(entry.created_at) > window:
        raise Forbidden(
            "Запись старше суток — исправить её может только администратор клуба",
            code="edit_window_closed",
        )


def get_entry(session, entry_id: int) -> ReadingEntry:
    entry = session.get(ReadingEntry, entry_id)
    if entry is None or entry.deleted_at is not None:
        raise NotFound("Запись не найдена")
    return entry


def update_entry(
    session,
    entry: ReadingEntry,
    actor: Member,
    *,
    pages: Optional[int] = None,
    note: Optional[str] = None,
    entry_date: Optional[date] = None,
    book_id: Optional[int] = ...,  # type: ignore[assignment]
) -> dict[str, Any]:
    _assert_can_edit(entry, actor)
    before = total_pages_of(session, entry.member_id)

    if pages is not None:
        pages_value = int(pages)
        if pages_value < 1:
            raise DomainError("Страниц должно быть хотя бы одна", code="pages_not_positive")
        hard_max = current_app.config["ENTRY_PAGES_HARD_MAX"]
        if pages_value > hard_max:
            raise DomainError(f"Больше {hard_max} страниц за запись — это опечатка",
                              code="pages_too_big")
        entry.pages = pages_value
        entry.input_kind = "pages"
        entry.input_value = float(pages_value)
        if not actor.is_admin:
            entry.is_flagged, entry.flag_reason = _flag_for(pages_value)

    if note is not None:
        entry.note = note.strip() or None
    if entry_date is not None:
        entry.entry_date = _validate_date(entry_date)
    if book_id is not ...:
        owner = session.get(Member, entry.member_id)
        book = _resolve_book(session, owner, book_id)
        entry.book_id = book.id if book else None

    session.flush()
    after = total_pages_of(session, entry.member_id)
    level_up = _level_change(session, entry.member_id, before, after)
    return {"entry": entry, "level_up": level_up}


def delete_entry(session, entry: ReadingEntry, actor: Member) -> None:
    _assert_can_edit(entry, actor)
    entry.deleted_at = utcnow()
    session.flush()


def finish_book(session, book: Book, actor: Member) -> Book:
    """«Книга дочитана»: уходит на полку прочитанного, поле текущей книги очищается."""
    if book.member_id != actor.id and not actor.is_admin:
        raise Forbidden("Это книга другого участника")
    if book.status == "finished":
        raise DomainError("Книга уже отмечена как дочитанная", code="already_finished")
    book.status = "finished"
    book.finished_at = msk_today()
    session.flush()
    events.record(
        session,
        "book_finished",
        book.member_id,
        {"book_id": book.id, "author": book.author, "title": book.title},
    )
    return book
