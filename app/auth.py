"""Доступ без паролей и почты.

Схема: персональная ссылка с токеном + четырёхзначный PIN, который участник
придумывает сам при первом входе. Дальше — подписанная cookie на 90 дней.

Для будущего чат-бота и мобильного приложения тот же вход отдаёт session_token,
который передаётся заголовком Authorization: Bearer <token>.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from functools import wraps
from typing import Optional

from flask import current_app, g, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from .domain.errors import Forbidden, Unauthorized
from .domain.time_utils import as_utc
from .extensions import db
from .models import Member, utcnow

CSRF_COOKIE = "chitkod_csrf"
TOKEN_PREFIX_LEN = 8


# --- токены персональных ссылок -------------------------------------------------

def issue_token() -> tuple[str, str, str]:
    """Новый токен: (открытый токен для ссылки, префикс для поиска, хеш для хранения)."""
    raw = secrets.token_urlsafe(24)
    return raw, raw[:TOKEN_PREFIX_LEN], hash_token(raw)


def hash_token(raw: str) -> str:
    # Токен длинный и случайный, поэтому достаточно быстрого хеша — в отличие от PIN
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def find_member_by_token(raw_token: str) -> Optional[Member]:
    if not raw_token:
        return None
    prefix = raw_token[:TOKEN_PREFIX_LEN]
    candidates = db.session.query(Member).filter(Member.token_prefix == prefix).all()
    digest = hash_token(raw_token)
    for member in candidates:
        if hmac.compare_digest(member.token_hash, digest):
            return member if member.is_active else None
    return None


def member_link(raw_token: str) -> str:
    return f"{current_app.config['PUBLIC_BASE_URL']}/enter/{raw_token}"


# --- PIN ------------------------------------------------------------------------

def validate_pin_format(pin: str) -> None:
    from .domain.errors import DomainError

    if not (pin and pin.isdigit() and len(pin) == 4):
        raise DomainError("PIN — это ровно четыре цифры", code="pin_format")
    if len(set(pin)) == 1:
        raise DomainError("Четыре одинаковые цифры слишком просто — придумайте другой PIN",
                          code="pin_too_simple")


def set_pin(member: Member, pin: str) -> None:
    validate_pin_format(pin)
    member.pin_hash = generate_password_hash(pin)
    member.pin_set_at = utcnow()
    member.failed_attempts = 0
    member.locked_until = None


def check_pin(member: Member, pin: str) -> bool:
    """Проверить PIN с защитой от перебора: 5 попыток, потом пауза 15 минут."""
    if member.locked_until and as_utc(member.locked_until) > utcnow():
        raise Forbidden(
            "Слишком много попыток. Попробуйте через несколько минут.", code="pin_locked"
        )
    if not member.pin_hash:
        return False

    if check_password_hash(member.pin_hash, pin or ""):
        member.failed_attempts = 0
        member.locked_until = None
        db.session.commit()
        return True

    member.failed_attempts += 1
    if member.failed_attempts >= current_app.config["PIN_MAX_ATTEMPTS"]:
        member.locked_until = utcnow() + current_app.config["PIN_LOCKOUT"]
        member.failed_attempts = 0
    db.session.commit()
    return False


# --- сессия ---------------------------------------------------------------------

def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="chitkod-session")


def make_session_token(member: Member) -> tuple[str, str]:
    """Подписанный токен сессии и связанный с ним CSRF-секрет."""
    csrf = secrets.token_urlsafe(16)
    payload = {"mid": member.id, "av": member.auth_version, "csrf": csrf}
    return _serializer().dumps(payload), csrf


def read_session_token(token: str) -> Optional[dict]:
    max_age = int(current_app.config["SESSION_MAX_AGE"].total_seconds())
    try:
        return _serializer().loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None


def apply_session_cookies(response, session_token: str, csrf: str):
    secure = current_app.config["COOKIE_SECURE"]
    max_age = int(current_app.config["SESSION_MAX_AGE"].total_seconds())
    response.set_cookie(
        current_app.config["SESSION_COOKIE_NAME"],
        session_token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="Lax",
        path="/",
    )
    # CSRF-cookie читается скриптом намеренно — она нужна фронтенду для заголовка
    response.set_cookie(
        CSRF_COOKIE, csrf, max_age=max_age, httponly=False, secure=secure,
        samesite="Lax", path="/",
    )
    return response


def clear_session_cookies(response):
    response.delete_cookie(current_app.config["SESSION_COOKIE_NAME"], path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response


# --- определение текущего участника ---------------------------------------------

def load_current_member() -> None:
    """before_request: положить участника в g.member и запомнить способ входа."""
    g.member = None
    g.auth_kind = None
    g.session_csrf = None

    bearer = request.headers.get("Authorization", "")
    raw = None
    if bearer.lower().startswith("bearer "):
        raw, kind = bearer[7:].strip(), "bearer"
    else:
        cookie = request.cookies.get(current_app.config["SESSION_COOKIE_NAME"])
        if cookie:
            raw, kind = cookie, "cookie"

    if not raw:
        return

    payload = read_session_token(raw)
    if not payload:
        return

    member = db.session.get(Member, payload.get("mid"))
    if member is None or not member.is_active:
        return
    if member.auth_version != payload.get("av"):
        return  # доступ отозван администратором

    g.member = member
    g.auth_kind = kind
    g.session_csrf = payload.get("csrf")


def current_member() -> Optional[Member]:
    return getattr(g, "member", None)


def _check_csrf() -> None:
    """Cookie-вход требует заголовок X-CSRF-Token. Bearer — нет: он не отправляется браузером сам."""
    if getattr(g, "auth_kind", None) != "cookie":
        return
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    sent = request.headers.get("X-CSRF-Token", "")
    expected = getattr(g, "session_csrf", None)
    if not expected or not hmac.compare_digest(sent, expected):
        raise Forbidden("Сессия устарела — обновите страницу", code="csrf")


def require_member(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if current_member() is None:
            raise Unauthorized("Войдите по своей персональной ссылке")
        _check_csrf()
        return view(*args, **kwargs)

    return wrapper


def require_admin(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        member = current_member()
        if member is None:
            raise Unauthorized("Войдите по своей персональной ссылке")
        if not member.is_admin:
            raise Forbidden("Доступ только для администратора клуба")
        _check_csrf()
        return view(*args, **kwargs)

    return wrapper


def assert_owner(member_id: int) -> Member:
    """Ключевая проверка: писать можно только в свою строку. Админ — исключение."""
    actor = current_member()
    if actor is None:
        raise Unauthorized("Войдите по своей персональной ссылке")
    if actor.id != member_id and not actor.is_admin:
        raise Forbidden("Редактировать можно только свою строку")
    return actor
