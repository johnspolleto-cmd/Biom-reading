"""Лента событий клуба."""

from __future__ import annotations

from typing import Any, Optional

import sqlalchemy as sa

from ..models import ClubEvent


def record(session, kind: str, member_id: Optional[int], payload: dict[str, Any]) -> ClubEvent:
    event = ClubEvent(kind=kind, member_id=member_id, payload=payload)
    session.add(event)
    return event


def feed(session, limit: int = 30) -> list[dict[str, Any]]:
    events = (
        session.execute(sa.select(ClubEvent).order_by(ClubEvent.created_at.desc()).limit(limit))
        .scalars()
        .all()
    )
    return [event.to_dict() for event in events]
