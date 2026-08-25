"""Страницы клуба.

Фронтенд — тонкий клиент: все изменения данных уходят в /api/v1/*, а сюда
возвращаются только за отрисованным HTML. Поэтому чат-боту и мобильному
приложению позже не понадобится ни строчки из этого файла.
"""

from __future__ import annotations

import sqlalchemy as sa
from flask import Blueprint, current_app, render_template, request

from .auth import current_member, find_member_by_token
from .domain import challenges as ch
from .domain import events, leaderboard
from .domain.levels import load_levels
from .domain.time_utils import as_utc, current_week_start, msk_today, week_range
from .extensions import db
from .models import Book, Quote, ReadingEntry, utcnow

views_bp = Blueprint("views", __name__)


def _board_context() -> dict:
    week = current_week_start()
    start, end = week_range(week)
    return {
        "rows": leaderboard.build_rows(db.session),
        "club": leaderboard.club_totals(db.session),
        "week": {"start": start, "end": end},
        "today": msk_today(),
    }


def _my_context() -> dict:
    """Данные для панели ввода: свои книги и последние записи."""
    member = current_member()
    if member is None:
        return {"my_books": [], "my_entries": []}
    books = (
        db.session.execute(
            sa.select(Book)
            .where(Book.member_id == member.id, Book.status == "reading")
            .order_by(Book.created_at.asc())
        )
        .scalars()
        .all()
    )
    entries = (
        db.session.execute(
            sa.select(ReadingEntry)
            .where(ReadingEntry.member_id == member.id, ReadingEntry.deleted_at.is_(None))
            .order_by(ReadingEntry.created_at.desc())
            .limit(10)
        )
        .scalars()
        .all()
    )
    # Свою запись можно править сутки — кнопку удаления показываем только у таких
    window = current_app.config["ENTRY_EDIT_WINDOW"]
    now = utcnow()
    editable = {e.id for e in entries if now - as_utc(e.created_at) <= window}
    return {"my_books": books, "my_entries": entries, "editable_entry_ids": editable}


@views_bp.get("/")
def index():
    challenge = ch.current_challenge(db.session)
    context = _board_context()
    context.update(_my_context())
    context.update(
        {
            "challenge": ch.with_results(db.session, challenge) if challenge else None,
            "feed": events.feed(db.session, 12),
            "levels": load_levels(db.session),
        }
    )
    return render_template("index.html", **context)


@views_bp.get("/board")
def board_partial():
    """Кусок HTML с таблицей — перерисовывается после каждой записи, с анимацией."""
    context = _board_context()
    context["sort"] = request.args.get("sort", "total")
    return render_template("_board.html", **context)


@views_bp.get("/quotes")
def quotes_page():
    quotes = (
        db.session.execute(sa.select(Quote).order_by(Quote.created_at.desc()).limit(300))
        .scalars()
        .all()
    )
    context = _my_context()
    return render_template("quotes.html", quotes=quotes, **context)


@views_bp.get("/challenges")
def challenges_page():
    return render_template(
        "challenges.html",
        current=ch.current_challenge(db.session)
        and ch.with_results(db.session, ch.current_challenge(db.session)),
        archive=ch.archive(db.session),
        upcoming=[c.to_dict() for c in ch.upcoming(db.session)],
        current_week=current_week_start(),
    )


@views_bp.get("/enter/", defaults={"token": ""})
@views_bp.get("/enter/<token>")
def enter(token: str):
    """Персональная ссылка: первый раз просим придумать PIN, дальше — ввести."""
    member = find_member_by_token(token)
    return render_template(
        "enter.html",
        token=token,
        found=member is not None,
        full_name=member.full_name if member else None,
        pin_is_set=member.pin_is_set if member else False,
    )


@views_bp.get("/admin")
def admin_page():
    member = current_member()
    if member is None or not member.is_admin:
        return render_template("error.html", message="Эта страница только для администратора клуба"), 403
    # Содержимое админки подтягивается из /api/v1/admin/* — здесь только каркас
    return render_template(
        "admin.html", current_week=current_week_start(), type_labels=ch.TYPE_LABELS
    )
