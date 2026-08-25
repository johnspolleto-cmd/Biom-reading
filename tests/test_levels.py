"""Уровни присваиваются ровно на границах 100 / 500 / 1000 / 2000 / 5000."""

from __future__ import annotations

import pytest

from app.domain.levels import level_for, load_levels
from app.extensions import db


@pytest.mark.parametrize(
    "total, expected",
    [
        (0, "Новичок"),
        (99, "Новичок"),
        (100, "Младенец"),      # граница включающая
        (101, "Младенец"),
        (499, "Младенец"),
        (500, "Первые шаги"),
        (999, "Первые шаги"),
        (1000, "Жёлтый рейнджер"),
        (1999, "Жёлтый рейнджер"),
        (2000, "Колобок"),
        (4999, "Колобок"),
        (5000, "Паучок"),
        (9999, "Паучок"),
        (10000, "Хранитель Биома"),
        (99999, "Хранитель Биома"),
    ],
)
def test_level_boundaries(app, total, expected):
    levels = load_levels(db.session)
    assert level_for(total, levels).name == expected


def test_progress_bar(app):
    levels = load_levels(db.session)

    # 300 страниц — ровно половина пути от 100 к 500
    half = level_for(300, levels)
    assert half.progress_pct == 50
    assert half.pages_to_next == 200
    assert half.next_name == "Первые шаги"

    # На самом пороге прогресс обнуляется и целью становится следующий уровень
    fresh = level_for(500, levels)
    assert fresh.progress_pct == 0
    assert fresh.next_name == "Жёлтый рейнджер"
    assert fresh.pages_to_next == 500


def test_top_level_has_no_next(app):
    levels = load_levels(db.session)
    top = level_for(12000, levels)
    assert top.next_name is None
    assert top.progress_pct == 100


def test_level_up_event_written(app, make_member, client):
    """Переход на уровень попадает в общую ленту клуба."""
    actor = make_member("Читатель")
    client.post("/api/v1/entries", json={"pages": 99}, headers=actor.headers)
    assert client.get("/api/v1/feed").get_json()["events"] == []

    client.post("/api/v1/entries", json={"pages": 1}, headers=actor.headers)
    events = client.get("/api/v1/feed").get_json()["events"]
    assert [e["type"] for e in events] == ["level_up"]
    assert events[0]["payload"]["level_name"] == "Младенец"
