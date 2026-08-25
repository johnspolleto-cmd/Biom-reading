"""Уровни читателя.

Пороги включающие: ровно 100 страниц — это уже «Младенец», а не «Новичок».
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from ..models import Level

# Стартовое наполнение таблицы levels. Дальше названия правятся в базе без деплоя.
# avatar_file — файл в app/static/levels/, положите туда свои картинки под теми же именами.
LEVEL_SEED: list[dict] = [
    {"idx": 0, "name": "Новичок", "threshold_pages": 0, "avatar_file": "level0.svg", "color_dark": "#6b7684", "color": "#94a3b8"},
    {"idx": 1, "name": "Младенец", "threshold_pages": 100, "avatar_file": "level1.svg", "color_dark": "#e39ac0", "color": "#f9a8d4"},
    {"idx": 2, "name": "Первые шаги", "threshold_pages": 500, "avatar_file": "level2.svg", "color_dark": "#6fc7ee", "color": "#7dd3fc"},
    {"idx": 3, "name": "Жёлтый рейнджер", "threshold_pages": 1000, "avatar_file": "level3.svg", "color_dark": "#e8c547", "color": "#facc15"},
    {"idx": 4, "name": "Колобок", "threshold_pages": 2000, "avatar_file": "level4.svg", "color_dark": "#e08a4a", "color": "#fb923c"},
    {"idx": 5, "name": "Паучок", "threshold_pages": 5000, "avatar_file": "level5.svg", "color_dark": "#a98cf0", "color": "#a78bfa"},
    {"idx": 6, "name": "Хранитель Биома", "threshold_pages": 10000, "avatar_file": "level6.svg", "color_dark": "#45d6a2", "color": "#34d399"},
]


@dataclass(frozen=True)
class LevelInfo:
    idx: int
    name: str
    threshold: int
    avatar: str
    color: str
    color_dark: str
    next_name: Optional[str]
    next_threshold: Optional[int]
    pages_to_next: Optional[int]
    progress_pct: int  # прогресс до следующего уровня, 0..100

    def to_dict(self) -> dict:
        return {
            "idx": self.idx,
            "name": self.name,
            "threshold": self.threshold,
            "avatar": self.avatar,
            "color": self.color,
            "color_dark": self.color_dark,
            "next_name": self.next_name,
            "next_threshold": self.next_threshold,
            "pages_to_next": self.pages_to_next,
            "progress_pct": self.progress_pct,
        }


def ensure_levels(session) -> None:
    """Создать недостающие уровни. Существующие не трогаем — их мог переименовать админ."""
    existing = {lvl.idx for lvl in session.query(Level).all()}
    for row in LEVEL_SEED:
        if row["idx"] not in existing:
            session.add(Level(**row))
    session.flush()


def load_levels(session) -> list[Level]:
    return session.query(Level).order_by(Level.threshold_pages.asc(), Level.idx.asc()).all()


def level_for(total_pages: int, levels: Iterable[Level]) -> LevelInfo:
    """Уровень по суммарным страницам за всё время + прогресс до следующего."""
    ordered = sorted(levels, key=lambda lvl: (lvl.threshold_pages, lvl.idx))
    if not ordered:
        raise RuntimeError("Таблица уровней пуста — выполните ensure_levels()")

    total = max(0, int(total_pages))
    current = ordered[0]
    nxt: Optional[Level] = None
    for lvl in ordered:
        if total >= lvl.threshold_pages:
            current = lvl
        else:
            nxt = lvl
            break

    if nxt is None:
        # Потолок достигнут — прогресс-бар заполнен
        return LevelInfo(
            idx=current.idx,
            name=current.name,
            threshold=current.threshold_pages,
            avatar=f"/static/levels/{current.avatar_file}",
            color=current.color,
            color_dark=current.color_dark,
            next_name=None,
            next_threshold=None,
            pages_to_next=None,
            progress_pct=100,
        )

    span = nxt.threshold_pages - current.threshold_pages
    done = total - current.threshold_pages
    pct = int(round(done * 100 / span)) if span > 0 else 100
    return LevelInfo(
        idx=current.idx,
        name=current.name,
        threshold=current.threshold_pages,
        avatar=f"/static/levels/{current.avatar_file}",
        color=current.color,
        color_dark=current.color_dark,
        next_name=nxt.name,
        next_threshold=nxt.threshold_pages,
        pages_to_next=nxt.threshold_pages - total,
        progress_pct=max(0, min(100, pct)),
    )
