"""REST API «ЧитКода».

Вся бизнес-логика живёт здесь, а не в шаблонах: страницы клуба, чат-бот и будущее
мобильное приложение ходят в одни и те же эндпоинты /api/v1/*.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from flask import Blueprint, request

from ..domain.errors import DomainError

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


def body() -> dict[str, Any]:
    """Тело запроса: JSON или обычная форма — фронтенд на HTMX шлёт форму."""
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.form.to_dict()


def as_int(raw: Any, field: str, *, required: bool = True) -> int | None:
    if raw in (None, ""):
        if required:
            raise DomainError(f"Поле «{field}» обязательно", code="field_required")
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise DomainError(f"Поле «{field}» должно быть числом", code="field_not_int")


def as_float(raw: Any, field: str, *, required: bool = True) -> float | None:
    if raw in (None, ""):
        if required:
            raise DomainError(f"Поле «{field}» обязательно", code="field_required")
        return None
    try:
        return float(str(raw).replace(",", "."))
    except (TypeError, ValueError):
        raise DomainError(f"Поле «{field}» должно быть числом", code="field_not_number")


def as_date(raw: Any, field: str) -> date | None:
    if raw in (None, ""):
        return None
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        raise DomainError(f"Поле «{field}» должно быть датой вида ГГГГ-ММ-ДД", code="field_not_date")


from . import admin, auth_api, member, public  # noqa: E402,F401
