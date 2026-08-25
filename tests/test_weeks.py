"""Недельная метрика: стык недель, нулевой знаменатель, стрик."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.domain.leaderboard import _streak_weeks, build_rows, weekly_dynamics
from app.domain.time_utils import MSK, week_bounds_utc, week_start
from app.extensions import db


def test_dynamics_growth():
    assert weekly_dynamics(260, 200).label == "+30 %"
    assert weekly_dynamics(260, 200).tone == "up"


def test_dynamics_decline():
    metric = weekly_dynamics(150, 300)
    assert metric.percent == -50
    assert metric.tone == "down"
    assert "50" in metric.label


def test_dynamics_zero_denominator_is_start():
    """Прошлая неделя 0, текущая больше 0 — «старт», а не деление на ноль."""
    metric = weekly_dynamics(120, 0)
    assert metric.kind == "start"
    assert metric.label == "старт"
    assert metric.percent is None


def test_dynamics_both_zero_is_pause():
    metric = weekly_dynamics(0, 0)
    assert metric.kind == "pause"
    assert metric.label == "пауза"


def test_dynamics_full_stop_is_minus_hundred():
    assert weekly_dynamics(0, 300).percent == -100


def test_week_starts_on_monday():
    # 2026-08-25 — вторник
    assert week_start(date(2026, 8, 25)) == date(2026, 8, 24)
    assert week_start(date(2026, 8, 24)) == date(2026, 8, 24)
    # воскресенье принадлежит той же неделе
    assert week_start(date(2026, 8, 30)) == date(2026, 8, 24)
    assert week_start(date(2026, 8, 31)) == date(2026, 8, 31)


def test_week_bounds_are_moscow_midnight():
    begin, end = week_bounds_utc(date(2026, 8, 24))
    # Понедельник 00:00 МСК — это воскресенье 21:00 UTC
    assert begin == datetime(2026, 8, 23, 21, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 30, 21, 0, tzinfo=timezone.utc)
    assert begin.astimezone(MSK).hour == 0


def test_week_boundary_splits_entries(app, make_member, add_pages, weeks):
    """Воскресенье и следующий понедельник попадают в разные недели."""
    actor = make_member("Пограничник")
    last_sunday = weeks["this"] - timedelta(days=1)
    add_pages(actor.id, 100, last_sunday)   # это прошлая неделя
    add_pages(actor.id, 40, weeks["this"])  # это уже текущая

    row = build_rows(db.session)[0]
    assert row["prev_week_pages"] == 100
    assert row["week_pages"] == 40
    assert row["dynamics"]["percent"] == -60


def test_streak_counts_consecutive_weeks(weeks):
    this_week = weeks["this"]
    prev = this_week - timedelta(days=7)
    before = this_week - timedelta(days=14)
    gap = this_week - timedelta(days=28)

    assert _streak_weeks({this_week, prev, before}, this_week) == 3
    # Текущая неделя ещё идёт — серия, оборвавшаяся «на сегодня», не считается разрывом
    assert _streak_weeks({prev, before}, this_week) == 2
    # Пропущенная неделя серию обрывает
    assert _streak_weeks({this_week, prev, gap}, this_week) == 2
    assert _streak_weeks(set(), this_week) == 0


def test_streak_in_row(app, make_member, add_pages, weeks):
    actor = make_member("Постоянный")
    for week in (weeks["this"], weeks["prev"], weeks["before"]):
        add_pages(actor.id, 30, week + timedelta(days=1))
    assert build_rows(db.session)[0]["streak_weeks"] == 3
