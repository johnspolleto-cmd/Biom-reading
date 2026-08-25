"""Челлендж недели.

Текущий челлендж не «публикуется по расписанию», а выбирается запросом по week_start.
Поэтому в понедельник 00:00 по Москве он сменяется сам — даже если планировщик лежал.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

import sqlalchemy as sa

from ..models import Book, Challenge, ChallengeResult, Member, ReadingEntry
from . import events
from .errors import DomainError, Forbidden, NotFound
from .time_utils import current_week_start, week_range

AUTO_TYPES = {"pages_total", "finish_book", "days_streak"}
TYPE_LABELS = {
    "pages_total": "Прочитать N страниц за неделю",
    "finish_book": "Дочитать книгу",
    "days_streak": "Читать N дней подряд",
    "genre": "Прочитать что-нибудь из жанра",
}


def challenge_for_week(session, week: date) -> Optional[Challenge]:
    return session.execute(
        sa.select(Challenge).where(Challenge.week_start == week, Challenge.is_published.is_(True))
    ).scalar_one_or_none()


def current_challenge(session) -> Optional[Challenge]:
    return challenge_for_week(session, current_week_start())


def upcoming(session, limit: int = 8) -> list[Challenge]:
    return (
        session.execute(
            sa.select(Challenge)
            .where(Challenge.week_start > current_week_start())
            .order_by(Challenge.week_start.asc())
            .limit(limit)
        )
        .scalars()
        .all()
    )


def progress_for(session, challenge: Challenge, member_id: int) -> int:
    """Насколько участник продвинулся в челлендже за его неделю."""
    start, end = week_range(challenge.week_start)

    if challenge.kind == "pages_total":
        return int(
            session.execute(
                sa.select(sa.func.coalesce(sa.func.sum(ReadingEntry.pages), 0)).where(
                    ReadingEntry.member_id == member_id,
                    ReadingEntry.deleted_at.is_(None),
                    ReadingEntry.entry_date >= start,
                    ReadingEntry.entry_date <= end,
                )
            ).scalar_one()
        )

    if challenge.kind == "days_streak":
        return int(
            session.execute(
                sa.select(sa.func.count(sa.distinct(ReadingEntry.entry_date))).where(
                    ReadingEntry.member_id == member_id,
                    ReadingEntry.deleted_at.is_(None),
                    ReadingEntry.entry_date >= start,
                    ReadingEntry.entry_date <= end,
                )
            ).scalar_one()
        )

    if challenge.kind == "finish_book":
        return int(
            session.execute(
                sa.select(sa.func.count(Book.id)).where(
                    Book.member_id == member_id,
                    Book.status == "finished",
                    Book.finished_at >= start,
                    Book.finished_at <= end,
                )
            ).scalar_one()
        )

    return 0  # «мягкий» челлендж — прогресс не измеряется автоматически


def target_of(challenge: Challenge) -> int:
    if challenge.kind == "finish_book":
        return challenge.target_value or 1
    if challenge.kind == "days_streak":
        return challenge.target_value or 5
    return challenge.target_value or 0


def _result_row(session, challenge: Challenge, member_id: int) -> ChallengeResult:
    row = session.execute(
        sa.select(ChallengeResult).where(
            ChallengeResult.challenge_id == challenge.id,
            ChallengeResult.member_id == member_id,
        )
    ).scalar_one_or_none()
    if row is None:
        row = ChallengeResult(challenge_id=challenge.id, member_id=member_id, status="pending")
        session.add(row)
        session.flush()
    return row


def recompute_member(session, challenge: Challenge, member_id: int) -> bool:
    """Пересчитать один числовой челлендж для одного участника.

    Вызывается прямо при добавлении записи, поэтому бейдж появляется без задержки.
    Возвращает True, если челлендж засчитан именно сейчас.
    """
    if not challenge.is_auto:
        return False

    target = target_of(challenge)
    value = progress_for(session, challenge, member_id)
    row = _result_row(session, challenge, member_id)
    row.progress_value = value
    achieved = target > 0 and value >= target

    if achieved and row.status != "completed":
        row.status = "completed"
        events.record(
            session,
            "challenge_won",
            member_id,
            {"challenge_id": challenge.id, "title": challenge.title,
             "week_start": challenge.week_start.isoformat()},
        )
        session.flush()
        return True

    if not achieved and row.status == "completed":
        # Запись отменили или удалили — бейдж честно снимаем
        row.status = "pending"
    session.flush()
    return False


def recompute(session, challenge: Optional[Challenge] = None) -> list[int]:
    """Пересчитать числовой челлендж для всех. Возвращает id засчитанных впервые."""
    challenge = challenge or current_challenge(session)
    if challenge is None or not challenge.is_auto:
        return []

    members = (
        session.execute(sa.select(Member).where(Member.is_active.is_(True))).scalars().all()
    )
    return [m.id for m in members if recompute_member(session, challenge, m.id)]


def claim(session, challenge: Challenge, member: Member) -> ChallengeResult:
    """Участник сам отмечает выполнение «мягкого» челленджа — админ подтвердит."""
    if challenge.is_auto:
        raise DomainError(
            "Этот челлендж засчитывается автоматически по журналу чтения",
            code="challenge_is_auto",
        )
    row = _result_row(session, challenge, member.id)
    if row.status == "completed":
        raise DomainError("Челлендж уже засчитан", code="already_completed")
    row.status = "claimed"
    session.flush()
    return row


def moderate(session, result_id: int, admin: Member, approve: bool) -> ChallengeResult:
    if not admin.is_admin:
        raise Forbidden("Подтверждать челленджи может только администратор")
    row = session.get(ChallengeResult, result_id)
    if row is None:
        raise NotFound("Отметка о челлендже не найдена")
    row.status = "completed" if approve else "rejected"
    row.confirmed_by = admin.id
    row.confirmed_at = sa.func.now()
    if approve:
        events.record(
            session,
            "challenge_won",
            row.member_id,
            {"challenge_id": row.challenge_id, "title": row.challenge.title,
             "week_start": row.challenge.week_start.isoformat()},
        )
    session.flush()
    return row


def with_results(session, challenge: Challenge) -> dict[str, Any]:
    winners = (
        session.execute(
            sa.select(ChallengeResult)
            .where(
                ChallengeResult.challenge_id == challenge.id,
                ChallengeResult.status == "completed",
            )
            .order_by(ChallengeResult.progress_value.desc())
        )
        .scalars()
        .all()
    )
    data = challenge.to_dict()
    data["target"] = target_of(challenge)
    data["winners"] = [
        {"member_id": w.member_id,
         "member_name": w.member.full_name if w.member else None,
         "progress_value": w.progress_value}
        for w in winners
    ]
    data["winners_count"] = len(winners)
    return data


def archive(session, limit: int = 52) -> list[dict[str, Any]]:
    challenges = (
        session.execute(
            sa.select(Challenge)
            .where(Challenge.week_start <= current_week_start())
            .order_by(Challenge.week_start.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [with_results(session, ch) for ch in challenges]


def pending_moderation(session) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            sa.select(ChallengeResult).where(ChallengeResult.status == "claimed")
        )
        .scalars()
        .all()
    )
    return [
        {**row.to_dict(), "challenge_title": row.challenge.title,
         "week_start": row.challenge.week_start.isoformat()}
        for row in rows
    ]


def close_out_previous_week(session) -> int:
    """Подвести итоги прошедшей недели: досчитать её челлендж. Возвращает число победителей."""
    prev = current_week_start() - timedelta(days=7)
    challenge = challenge_for_week(session, prev)
    if challenge is None:
        return 0
    recompute(session, challenge)
    return int(
        session.execute(
            sa.select(sa.func.count(ChallengeResult.id)).where(
                ChallengeResult.challenge_id == challenge.id,
                ChallengeResult.status == "completed",
            )
        ).scalar_one()
    )
