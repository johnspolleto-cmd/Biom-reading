"""Время. В базе всё в UTC, недели и «сегодня» считаются по Москве.

Неделя клуба: понедельник 00:00 — воскресенье 23:59:59 по Europe/Moscow.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime) -> datetime:
    """Привести время из базы к UTC.

    PostgreSQL возвращает timestamptz с зоной, SQLite (тесты) — наивное время.
    Пишем мы всегда UTC, поэтому наивное трактуем как UTC.
    """
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def to_msk(dt: datetime) -> datetime:
    """Перевести момент времени в московское. Наивное время считаем UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MSK)


def msk_now() -> datetime:
    return utcnow().astimezone(MSK)


def msk_today() -> date:
    """Сегодняшняя дата по Москве. В 23:30 UTC воскресенья это уже понедельник."""
    return msk_now().date()


def week_start(day: date) -> date:
    """Понедельник той недели, в которую попадает day."""
    return day - timedelta(days=day.weekday())


def current_week_start() -> date:
    return week_start(msk_today())


def previous_week_start() -> date:
    return current_week_start() - timedelta(days=7)


def week_range(start: date) -> tuple[date, date]:
    """Границы недели включительно: (понедельник, воскресенье)."""
    return start, start + timedelta(days=6)


def week_bounds_utc(start: date) -> tuple[datetime, datetime]:
    """Границы недели как моменты в UTC: [понедельник 00:00 МСК, следующий понедельник 00:00 МСК)."""
    begin = datetime.combine(start, time.min, tzinfo=MSK)
    end = datetime.combine(start + timedelta(days=7), time.min, tzinfo=MSK)
    return begin.astimezone(timezone.utc), end.astimezone(timezone.utc)


def format_msk(dt: datetime, fmt: str = "%d.%m.%Y %H:%M") -> str:
    return to_msk(dt).strftime(fmt)
