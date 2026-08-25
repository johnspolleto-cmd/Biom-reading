"""Рейтинг клуба.

Ничего не кэшируется: все показатели — агрегация из reading_entries на лету.
На несколько десятков участников это единицы миллисекунд, зато рассинхрону взяться неоткуда.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional

import sqlalchemy as sa

from ..models import Book, Challenge, ChallengeResult, Member, Quote, ReadingEntry
from .levels import level_for, load_levels
from .time_utils import as_utc, current_week_start, previous_week_start, week_range


@dataclass(frozen=True)
class WeeklyDynamics:
    """Недельная динамика: (текущая − прошлая) / прошлая × 100 %."""

    kind: str  # growth | start | pause
    percent: Optional[int]
    label: str
    tone: str  # up | down | flat | start | pause

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "percent": self.percent, "label": self.label, "tone": self.tone}


def weekly_dynamics(this_week: int, prev_week: int) -> WeeklyDynamics:
    """Правила из ТЗ, включая оба случая нулевого знаменателя."""
    if prev_week == 0 and this_week == 0:
        return WeeklyDynamics("pause", None, "пауза", "pause")
    if prev_week == 0:
        # Делить на ноль нельзя, и «+∞ %» — не ответ
        return WeeklyDynamics("start", None, "старт", "start")

    pct = int(round((this_week - prev_week) * 100 / prev_week))
    if pct > 0:
        return WeeklyDynamics("growth", pct, f"+{pct} %", "up")
    if pct < 0:
        return WeeklyDynamics("growth", pct, f"−{abs(pct)} %", "down")
    return WeeklyDynamics("growth", 0, "0 %", "flat")


def _streak_weeks(weeks: set[date], this_week: date) -> int:
    """Сколько недель подряд человек читал.

    Текущая неделя ещё не закончилась, поэтому серия, оборвавшаяся «на сегодня»,
    не считается разрывом: если на этой неделе записей пока нет, смотрим серию,
    заканчивающуюся прошлой неделей.
    """
    if not weeks:
        return 0
    anchor = this_week if this_week in weeks else this_week - timedelta(days=7)
    if anchor not in weeks:
        return 0
    count = 0
    cursor = anchor
    while cursor in weeks:
        count += 1
        cursor -= timedelta(days=7)
    return count


def _sum_by_member(session, start: date, end: date) -> dict[int, int]:
    rows = session.execute(
        sa.select(ReadingEntry.member_id, sa.func.coalesce(sa.func.sum(ReadingEntry.pages), 0))
        .where(
            ReadingEntry.deleted_at.is_(None),
            ReadingEntry.entry_date >= start,
            ReadingEntry.entry_date <= end,
        )
        .group_by(ReadingEntry.member_id)
    ).all()
    return {member_id: int(total) for member_id, total in rows}


def build_rows(session, *, week_start: Optional[date] = None) -> list[dict[str, Any]]:
    """Полные строки таблицы для всех активных участников, отсортированные по рейтингу."""
    this_week = week_start or current_week_start()
    prev_week = this_week - timedelta(days=7)

    members = (
        session.execute(
            sa.select(Member).where(Member.is_active.is_(True)).order_by(Member.full_name)
        )
        .scalars()
        .all()
    )
    if not members:
        return []

    levels = load_levels(session)

    totals_rows = session.execute(
        sa.select(
            ReadingEntry.member_id,
            sa.func.coalesce(sa.func.sum(ReadingEntry.pages), 0),
            sa.func.max(ReadingEntry.created_at),
            sa.func.count(ReadingEntry.id),
        )
        .where(ReadingEntry.deleted_at.is_(None))
        .group_by(ReadingEntry.member_id)
    ).all()
    totals: dict[int, int] = {}
    last_at: dict[int, datetime] = {}
    entry_counts: dict[int, int] = {}
    for member_id, total, last, cnt in totals_rows:
        totals[member_id] = int(total)
        last_at[member_id] = last
        entry_counts[member_id] = int(cnt)

    cur_sums = _sum_by_member(session, *week_range(this_week))
    prev_sums = _sum_by_member(session, *week_range(prev_week))

    # Недели с хотя бы одной записью — для стрика
    week_rows = session.execute(
        sa.select(ReadingEntry.member_id, ReadingEntry.entry_date)
        .where(ReadingEntry.deleted_at.is_(None))
        .distinct()
    ).all()
    weeks_by_member: dict[int, set[date]] = {}
    for member_id, entry_date in week_rows:
        weeks_by_member.setdefault(member_id, set()).add(
            entry_date - timedelta(days=entry_date.weekday())
        )

    finished_rows = session.execute(
        sa.select(Book.member_id, sa.func.count(Book.id))
        .where(Book.status == "finished")
        .group_by(Book.member_id)
    ).all()
    finished_counts = {member_id: int(cnt) for member_id, cnt in finished_rows}

    current_books = {
        book.member_id: book
        for book in session.execute(
            sa.select(Book)
            .where(Book.status == "reading")
            .order_by(Book.member_id, Book.created_at.asc())
        )
        .scalars()
        .all()
    }

    quotes_by_member: dict[int, list[Quote]] = {}
    for quote in (
        session.execute(sa.select(Quote).order_by(Quote.created_at.desc())).scalars().all()
    ):
        quotes_by_member.setdefault(quote.member_id, []).append(quote)

    badges_by_member = _badges(session, this_week)

    rows: list[dict[str, Any]] = []
    for member in members:
        total = totals.get(member.id, 0)
        cur = cur_sums.get(member.id, 0)
        prev = prev_sums.get(member.id, 0)
        level = level_for(total, levels)
        quotes = quotes_by_member.get(member.id, [])
        book = current_books.get(member.id)

        rows.append(
            {
                "member_id": member.id,
                "full_name": member.full_name,
                "is_admin": member.is_admin,
                "joined_at": member.joined_at.isoformat(),
                "total_pages": total,
                "entries_count": entry_counts.get(member.id, 0),
                "books_finished": finished_counts.get(member.id, 0),
                "current_book": book.to_dict() if book else None,
                "level": level.to_dict(),
                "week_pages": cur,
                "prev_week_pages": prev,
                "dynamics": weekly_dynamics(cur, prev).to_dict(),
                "streak_weeks": _streak_weeks(weeks_by_member.get(member.id, set()), this_week),
                "last_quote": quotes[0].to_dict() if quotes else None,
                "quotes_count": len(quotes),
                "quotes": [q.to_dict() for q in quotes],
                "badges": badges_by_member.get(member.id, []),
                # служебное поле для тай-брейка, наружу не отдаём
                "_last_entry_at": last_at.get(member.id),
            }
        )

    rows.sort(key=_sort_key)
    for position, row in enumerate(rows, start=1):
        row["rank"] = position
        row.pop("_last_entry_at", None)
    return rows


def _sort_key(row: dict[str, Any]):
    """Сортировка: по сумме убыв., при равенстве выше тот, кто достиг результата раньше."""
    last = row.get("_last_entry_at")
    # У кого записей нет — в самый низ своей группы
    never_read = last is None
    stamp = as_utc(last).timestamp() if last is not None else 0.0
    return (-row["total_pages"], never_read, stamp, row["full_name"])


def _badges(session, this_week: date) -> dict[int, list[dict[str, Any]]]:
    """Бейджи выполненных челленджей: текущей недели — ярко, прошлых — счётчиком."""
    rows = session.execute(
        sa.select(ChallengeResult, Challenge)
        .join(Challenge, Challenge.id == ChallengeResult.challenge_id)
        .where(ChallengeResult.status == "completed")
    ).all()
    out: dict[int, list[dict[str, Any]]] = {}
    for result, challenge in rows:
        out.setdefault(result.member_id, []).append(
            {
                "challenge_id": challenge.id,
                "title": challenge.title,
                "week_start": challenge.week_start.isoformat(),
                "is_current": challenge.week_start == this_week,
            }
        )
    for badges in out.values():
        badges.sort(key=lambda b: b["week_start"], reverse=True)
    return out


def member_row(session, member_id: int) -> Optional[dict[str, Any]]:
    for row in build_rows(session):
        if row["member_id"] == member_id:
            return row
    return None


def total_pages_of(session, member_id: int) -> int:
    return int(
        session.execute(
            sa.select(sa.func.coalesce(sa.func.sum(ReadingEntry.pages), 0)).where(
                ReadingEntry.member_id == member_id, ReadingEntry.deleted_at.is_(None)
            )
        ).scalar_one()
    )


def club_totals(session) -> dict[str, int]:
    """Сводка по клубу для шапки."""
    this_week = current_week_start()
    total = int(
        session.execute(
            sa.select(sa.func.coalesce(sa.func.sum(ReadingEntry.pages), 0)).where(
                ReadingEntry.deleted_at.is_(None)
            )
        ).scalar_one()
    )
    week_total = sum(_sum_by_member(session, *week_range(this_week)).values())
    members = int(
        session.execute(
            sa.select(sa.func.count(Member.id)).where(Member.is_active.is_(True))
        ).scalar_one()
    )
    books_done = int(
        session.execute(
            sa.select(sa.func.count(Book.id)).where(Book.status == "finished")
        ).scalar_one()
    )
    return {
        "total_pages": total,
        "week_pages": week_total,
        "members": members,
        "books_finished": books_done,
    }


__all__ = [
    "WeeklyDynamics",
    "weekly_dynamics",
    "build_rows",
    "member_row",
    "total_pages_of",
    "club_totals",
    "previous_week_start",
]
