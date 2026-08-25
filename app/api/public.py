"""Публичная часть API: таблицу видит любой по ссылке, в режиме чтения."""

from __future__ import annotations

import sqlalchemy as sa
from flask import jsonify, request

from ..domain import challenges as ch
from ..domain import events, leaderboard
from ..domain.errors import NotFound
from ..domain.levels import load_levels
from ..domain.time_utils import current_week_start, week_range
from ..extensions import db
from ..models import Book, Quote
from . import api_bp, as_date


@api_bp.get("/leaderboard")
def get_leaderboard():
    week = as_date(request.args.get("week"), "week") or current_week_start()
    rows = leaderboard.build_rows(db.session, week_start=week)
    start, end = week_range(week)
    return jsonify(
        {
            "week": {"start": start.isoformat(), "end": end.isoformat()},
            "club": leaderboard.club_totals(db.session),
            "rows": rows,
        }
    )


@api_bp.get("/members/<int:member_id>")
def get_member(member_id: int):
    row = leaderboard.member_row(db.session, member_id)
    if row is None:
        raise NotFound("Участник не найден")
    books = (
        db.session.execute(
            sa.select(Book).where(Book.member_id == member_id).order_by(Book.created_at.desc())
        )
        .scalars()
        .all()
    )
    row["books"] = [b.to_dict() for b in books]
    return jsonify(row)


@api_bp.get("/levels")
def get_levels():
    return jsonify({"levels": [lvl.to_dict() for lvl in load_levels(db.session)]})


@api_bp.get("/quotes")
def get_quotes():
    limit = min(int(request.args.get("limit", 100)), 500)
    query = sa.select(Quote).order_by(Quote.created_at.desc()).limit(limit)
    member_id = request.args.get("member_id")
    if member_id:
        query = (
            sa.select(Quote)
            .where(Quote.member_id == int(member_id))
            .order_by(Quote.created_at.desc())
            .limit(limit)
        )
    quotes = db.session.execute(query).scalars().all()
    return jsonify({"quotes": [q.to_dict() for q in quotes]})


@api_bp.get("/challenges/current")
def get_current_challenge():
    challenge = ch.current_challenge(db.session)
    if challenge is None:
        return jsonify({"challenge": None})
    return jsonify({"challenge": ch.with_results(db.session, challenge)})


@api_bp.get("/challenges")
def get_challenges():
    return jsonify(
        {
            "archive": ch.archive(db.session),
            "upcoming": [c.to_dict() for c in ch.upcoming(db.session)],
        }
    )


@api_bp.get("/feed")
def get_feed():
    limit = min(int(request.args.get("limit", 30)), 200)
    return jsonify({"events": events.feed(db.session, limit)})


@api_bp.get("/stats")
def get_stats():
    return jsonify(leaderboard.club_totals(db.session))
