"""Вступление в клуб по общему коду.

Клуб закрытый, но администратор не должен быть узким местом: он один раз
выкладывает ссылку с кодом в чат клуба, дальше люди добавляют себя сами.
"""

from __future__ import annotations

import secrets
import string

import sqlalchemy as sa
from flask import current_app

from ..models import ClubSettings, Member
from . import events
from .errors import DomainError, Forbidden
from .time_utils import msk_today

# Без похожих друг на друга знаков: код читают с экрана и диктуют голосом
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8


def generate_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def get_settings(session) -> ClubSettings:
    """Единственная строка настроек. Создаётся при первом обращении."""
    settings = session.get(ClubSettings, 1)
    if settings is None:
        settings = ClubSettings(id=1, join_code=generate_code(), join_enabled=True)
        session.add(settings)
        session.flush()
    return settings


def join_link(session) -> str:
    return f"{current_app.config['PUBLIC_BASE_URL']}/join/{get_settings(session).join_code}"


def rotate_code(session) -> ClubSettings:
    """Перевыпустить код. Старая ссылка перестаёт работать, участники остаются."""
    settings = get_settings(session)
    settings.join_code = generate_code()
    session.flush()
    return settings


def set_enabled(session, enabled: bool) -> ClubSettings:
    settings = get_settings(session)
    settings.join_enabled = bool(enabled)
    session.flush()
    return settings


def code_matches(session, code: str) -> bool:
    settings = get_settings(session)
    if not settings.join_enabled:
        return False
    return secrets.compare_digest((code or "").strip().upper(), settings.join_code)


def check_code(session, code: str) -> None:
    """Бросает понятную ошибку, если по коду вступить нельзя."""
    settings = get_settings(session)
    if not settings.join_enabled:
        raise Forbidden(
            "Набор в клуб сейчас закрыт. Напишите администратору.", code="join_disabled"
        )
    if not secrets.compare_digest((code or "").strip().upper(), settings.join_code):
        raise Forbidden(
            "Код клуба не подошёл. Попросите свежую ссылку — код могли перевыпустить.",
            code="join_bad_code",
        )


def normalize_name(raw: str) -> str:
    name = " ".join((raw or "").split())
    if len(name) < 2:
        raise DomainError("Напишите, как вас зовут", code="name_required")
    if len(name) > 160:
        raise DomainError("Слишком длинное имя", code="name_too_long")
    return name


def name_taken(session, name: str) -> bool:
    """Совпадение ФИО среди активных — почти всегда это повторное вступление.

    Сравниваем в Python, а не в SQL: встроенный lower() в SQLite не трогает
    кириллицу, в PostgreSQL трогает — регистронезависимость разъехалась бы
    между тестами и продакшеном.
    """
    target = name.casefold()
    names = session.execute(
        sa.select(Member.full_name).where(Member.is_active.is_(True))
    ).scalars()
    return any(existing.casefold() == target for existing in names)


def create_self_joined_member(session, name: str, token_prefix: str, token_hash: str) -> Member:
    member = Member(
        full_name=name,
        token_prefix=token_prefix,
        token_hash=token_hash,
        joined_at=msk_today(),
        self_joined=True,
    )
    session.add(member)
    session.flush()
    events.record(session, "joined", member.id, {"full_name": name, "self_joined": True})
    return member
