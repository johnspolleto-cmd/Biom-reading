from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from app import create_app
from app.auth import issue_token
from app.config import TestConfig
from app.domain.levels import ensure_levels
from app.domain.time_utils import MSK, current_week_start
from app.extensions import db
from app.models import Book, Member, ReadingEntry


@pytest.fixture
def app():
    application = create_app(TestConfig)
    with application.app_context():
        db.create_all()
        ensure_levels(db.session)
        db.session.commit()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


class Actor:
    """Участник вместе с готовым способом ходить в API от его имени."""

    def __init__(self, member_id: int, raw_token: str, session_token: str):
        self.id = member_id
        self.raw_token = raw_token
        self.session_token = session_token

    @property
    def headers(self) -> dict:
        # Bearer вместо cookie: так тест бьёт по API напрямую, в обход интерфейса
        return {"Authorization": f"Bearer {self.session_token}"}


@pytest.fixture
def make_member(app, client):
    def factory(full_name: str = "Тестовый Участник", *, admin: bool = False,
                pin: str = "2481") -> Actor:
        raw, prefix, digest = issue_token()
        member = Member(
            full_name=full_name,
            role="admin" if admin else "member",
            token_prefix=prefix,
            token_hash=digest,
            joined_at=date(2026, 1, 1),
        )
        db.session.add(member)
        db.session.commit()

        # Отдельный клиент: основной должен остаться «гостевым», без cookie,
        # чтобы тесты били по API напрямую с Bearer-токеном
        with app.test_client() as fresh:
            response = fresh.post("/api/v1/auth/set-pin", json={"token": raw, "pin": pin})
        assert response.status_code == 200, response.get_json()
        return Actor(member.id, raw, response.get_json()["session_token"])

    return factory


@pytest.fixture
def add_pages(app):
    """Записать страницы напрямую в базу — для подготовки истории в тестах."""

    def factory(member_id: int, pages: int, day: date, *, hour: int = 20,
                book_id: int | None = None) -> ReadingEntry:
        stamp = datetime.combine(day, time(hour, 0), tzinfo=MSK).astimezone(timezone.utc)
        entry = ReadingEntry(
            member_id=member_id,
            book_id=book_id,
            pages=pages,
            input_kind="pages",
            input_value=pages,
            entry_date=day,
            created_at=stamp,
            updated_at=stamp,
        )
        db.session.add(entry)
        db.session.commit()
        return entry

    return factory


@pytest.fixture
def make_book(app):
    def factory(member_id: int, title: str = "Книга", total_pages: int | None = 400) -> Book:
        book = Book(member_id=member_id, author="Автор", title=title,
                    total_pages=total_pages, status="reading")
        db.session.add(book)
        db.session.commit()
        return book

    return factory


@pytest.fixture
def weeks():
    """Понедельники текущей, прошлой и позапрошлой недели по Москве."""
    this_week = current_week_start()
    return {
        "this": this_week,
        "prev": this_week - timedelta(days=7),
        "before": this_week - timedelta(days=14),
    }
