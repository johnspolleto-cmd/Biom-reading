"""Личные действия участника. Писать можно только в свою строку."""

from __future__ import annotations

import sqlalchemy as sa
from flask import jsonify

from ..auth import assert_owner, current_member, require_member
from ..domain import challenges as ch
from ..domain import entries as entries_service
from ..domain import leaderboard
from ..domain.errors import DomainError, NotFound
from ..extensions import db
from ..models import Book, Quote, ReadingEntry
from . import api_bp, as_date, as_float, as_int, body


@api_bp.patch("/members/me")
@require_member
def update_me():
    member = current_member()
    data = body()
    name = str(data.get("full_name", "")).strip()
    if not name:
        raise DomainError("ФИО не может быть пустым", code="name_required")
    if len(name) > 160:
        raise DomainError("Слишком длинное имя", code="name_too_long")
    member.full_name = name
    db.session.commit()
    return jsonify({"member_id": member.id, "full_name": member.full_name})


@api_bp.get("/members/me/entries")
@require_member
def my_entries():
    member = current_member()
    rows = (
        db.session.execute(
            sa.select(ReadingEntry)
            .where(ReadingEntry.member_id == member.id, ReadingEntry.deleted_at.is_(None))
            .order_by(ReadingEntry.entry_date.desc(), ReadingEntry.created_at.desc())
            .limit(100)
        )
        .scalars()
        .all()
    )
    return jsonify({"entries": [e.to_dict() for e in rows]})


@api_bp.get("/members/me/books")
@require_member
def my_books():
    member = current_member()
    rows = (
        db.session.execute(
            sa.select(Book)
            .where(Book.member_id == member.id)
            .order_by(Book.status.asc(), Book.created_at.desc())
        )
        .scalars()
        .all()
    )
    return jsonify({"books": [b.to_dict() for b in rows]})


@api_bp.post("/entries")
@require_member
def create_entry():
    """Главное действие продукта: «+37 страниц»."""
    member = current_member()
    data = body()

    result = entries_service.add_entry(
        db.session,
        member,
        pages=as_int(data.get("pages"), "страницы", required=False),
        percent=as_float(data.get("percent"), "процент", required=False),
        book_id=as_int(data.get("book_id"), "книга", required=False),
        note=data.get("note"),
        entry_date=as_date(data.get("entry_date"), "дата"),
    )

    challenge = ch.current_challenge(db.session)
    challenge_done = False
    if challenge is not None:
        challenge_done = ch.recompute_member(db.session, challenge, member.id)

    db.session.commit()

    return (
        jsonify(
            {
                "entry": result["entry"].to_dict(),
                "level_up": result["level_up"],
                "challenge_done": challenge_done,
                "row": leaderboard.member_row(db.session, member.id),
            }
        ),
        201,
    )


@api_bp.patch("/entries/<int:entry_id>")
@require_member
def patch_entry(entry_id: int):
    actor = current_member()
    entry = entries_service.get_entry(db.session, entry_id)
    data = body()
    result = entries_service.update_entry(
        db.session,
        entry,
        actor,
        pages=as_int(data.get("pages"), "страницы", required=False),
        note=data.get("note"),
        entry_date=as_date(data.get("entry_date"), "дата"),
        book_id=as_int(data.get("book_id"), "книга", required=False) if "book_id" in data else ...,
    )
    challenge = ch.current_challenge(db.session)
    if challenge is not None:
        ch.recompute_member(db.session, challenge, entry.member_id)
    db.session.commit()
    return jsonify(
        {
            "entry": result["entry"].to_dict(),
            "level_up": result["level_up"],
            "row": leaderboard.member_row(db.session, entry.member_id),
        }
    )


@api_bp.delete("/entries/<int:entry_id>")
@require_member
def remove_entry(entry_id: int):
    actor = current_member()
    entry = entries_service.get_entry(db.session, entry_id)
    member_id = entry.member_id
    entries_service.delete_entry(db.session, entry, actor)
    challenge = ch.current_challenge(db.session)
    if challenge is not None:
        ch.recompute_member(db.session, challenge, member_id)
    db.session.commit()
    return jsonify({"ok": True, "row": leaderboard.member_row(db.session, member_id)})


@api_bp.post("/books")
@require_member
def create_book():
    member = current_member()
    data = body()
    title = str(data.get("title", "")).strip()
    if not title:
        raise DomainError("Название книги обязательно", code="title_required")
    fmt = str(data.get("format", "paper"))
    if fmt not in {"paper", "ebook"}:
        raise DomainError("Формат книги — «paper» или «ebook»", code="bad_format")

    # Текущая книга одна: предыдущую «в процессе» переводим в прочитанные вручную,
    # поэтому просто разрешаем несколько, а в строке показываем самую раннюю начатую.
    book = Book(
        member_id=member.id,
        author=str(data.get("author", "")).strip(),
        title=title,
        total_pages=as_int(data.get("total_pages"), "объём", required=False),
        fmt=fmt,
        status="reading",
        started_at=as_date(data.get("started_at"), "дата начала"),
    )
    db.session.add(book)
    db.session.commit()
    return jsonify({"book": book.to_dict()}), 201


@api_bp.patch("/books/<int:book_id>")
@require_member
def patch_book(book_id: int):
    book = db.session.get(Book, book_id)
    if book is None:
        raise NotFound("Книга не найдена")
    assert_owner(book.member_id)
    data = body()
    if "author" in data:
        book.author = str(data["author"]).strip()
    if "title" in data:
        title = str(data["title"]).strip()
        if not title:
            raise DomainError("Название книги обязательно", code="title_required")
        book.title = title
    if "total_pages" in data:
        book.total_pages = as_int(data["total_pages"], "объём", required=False)
    if "format" in data and data["format"] in {"paper", "ebook"}:
        book.fmt = data["format"]
    db.session.commit()
    return jsonify({"book": book.to_dict()})


@api_bp.post("/books/<int:book_id>/finish")
@require_member
def finish_book(book_id: int):
    """«Книга дочитана»: на полку прочитанного, счётчик книг +1, текущая книга очищается."""
    actor = current_member()
    book = db.session.get(Book, book_id)
    if book is None:
        raise NotFound("Книга не найдена")
    entries_service.finish_book(db.session, book, actor)

    challenge = ch.current_challenge(db.session)
    challenge_done = False
    if challenge is not None:
        challenge_done = ch.recompute_member(db.session, challenge, book.member_id)

    db.session.commit()
    return jsonify(
        {
            "book": book.to_dict(),
            "challenge_done": challenge_done,
            "row": leaderboard.member_row(db.session, book.member_id),
        }
    )


@api_bp.post("/quotes")
@require_member
def create_quote():
    member = current_member()
    data = body()
    text = str(data.get("text", "")).strip()
    if not text:
        raise DomainError("Цитата не может быть пустой", code="text_required")
    if len(text) > 2000:
        raise DomainError("Цитата длиннее 2000 знаков — сократите", code="text_too_long")

    book_id = as_int(data.get("book_id"), "книга", required=False)
    book_label = str(data.get("book_label", "")).strip()
    if book_id:
        book = db.session.get(Book, book_id)
        if book is None or book.member_id != member.id:
            raise NotFound("Книга не найдена")
        book_label = book.label

    quote = Quote(
        member_id=member.id,
        book_id=book_id,
        book_label=book_label,
        text=text,
        page=as_int(data.get("page"), "страница", required=False),
    )
    db.session.add(quote)
    db.session.commit()
    return jsonify({"quote": quote.to_dict()}), 201


@api_bp.patch("/quotes/<int:quote_id>")
@require_member
def patch_quote(quote_id: int):
    """Свою цитату можно править сколько угодно: это не результат, а находка."""
    quote = db.session.get(Quote, quote_id)
    if quote is None:
        raise NotFound("Цитата не найдена")
    assert_owner(quote.member_id)
    data = body()

    if "text" in data:
        text = str(data["text"]).strip()
        if not text:
            raise DomainError("Цитата не может быть пустой", code="text_required")
        if len(text) > 2000:
            raise DomainError("Цитата длиннее 2000 знаков — сократите", code="text_too_long")
        quote.text = text

    if "page" in data:
        quote.page = as_int(data["page"], "страница", required=False)

    if "book_id" in data:
        book_id = as_int(data["book_id"], "книга", required=False)
        if book_id:
            book = db.session.get(Book, book_id)
            if book is None or book.member_id != quote.member_id:
                raise NotFound("Книга не найдена")
            quote.book_id = book.id
            quote.book_label = book.label
        else:
            quote.book_id = None
            quote.book_label = str(data.get("book_label", quote.book_label)).strip()
    elif "book_label" in data:
        quote.book_label = str(data["book_label"]).strip()

    db.session.commit()
    return jsonify({"quote": quote.to_dict()})


@api_bp.get("/quotes/<int:quote_id>")
@require_member
def get_quote(quote_id: int):
    quote = db.session.get(Quote, quote_id)
    if quote is None:
        raise NotFound("Цитата не найдена")
    assert_owner(quote.member_id)
    return jsonify({"quote": quote.to_dict()})


@api_bp.delete("/quotes/<int:quote_id>")
@require_member
def remove_quote(quote_id: int):
    quote = db.session.get(Quote, quote_id)
    if quote is None:
        raise NotFound("Цитата не найдена")
    assert_owner(quote.member_id)
    db.session.delete(quote)
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.post("/challenges/<int:challenge_id>/claim")
@require_member
def claim_challenge(challenge_id: int):
    """«Мягкий» челлендж участник отмечает сам, админ подтверждает."""
    member = current_member()
    challenge = db.session.get(ch.Challenge, challenge_id)
    if challenge is None:
        raise NotFound("Челлендж не найден")
    row = ch.claim(db.session, challenge, member)
    db.session.commit()
    return jsonify({"result": row.to_dict()})
