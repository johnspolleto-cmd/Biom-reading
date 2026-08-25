"""Вход по персональной ссылке и PIN."""

from __future__ import annotations

from flask import current_app, jsonify, make_response

from .. import auth
from ..domain import club
from ..domain.errors import DomainError, Unauthorized
from ..extensions import db
from . import api_bp, body


def _me_payload(member) -> dict:
    return {
        "id": member.id,
        "full_name": member.full_name,
        "role": member.role,
        "is_admin": member.is_admin,
        "pin_is_set": member.pin_is_set,
    }


@api_bp.get("/auth/me")
def me():
    member = auth.current_member()
    if member is None:
        return jsonify({"member": None})
    return jsonify({"member": _me_payload(member)})


@api_bp.post("/auth/check-token")
def check_token():
    """Проверить ссылку до ввода PIN: показать имя и понять, задан ли уже PIN."""
    data = body()
    member = auth.find_member_by_token(str(data.get("token", "")))
    if member is None:
        raise Unauthorized("Ссылка недействительна. Попросите новую у администратора клуба.")
    return jsonify(
        {"full_name": member.full_name, "pin_is_set": member.pin_is_set, "member_id": member.id}
    )


@api_bp.post("/auth/set-pin")
def set_pin():
    """Первый вход: участник придумывает PIN сам."""
    data = body()
    member = auth.find_member_by_token(str(data.get("token", "")))
    if member is None:
        raise Unauthorized("Ссылка недействительна")
    if member.pin_is_set:
        raise DomainError(
            "PIN уже задан. Введите его или попросите администратора сбросить доступ.",
            code="pin_already_set",
        )
    pin = str(data.get("pin", ""))
    if pin != str(data.get("pin_repeat", pin)):
        raise DomainError("PIN и его повтор не совпали", code="pin_mismatch")

    auth.set_pin(member, pin)
    db.session.commit()
    return _login_response(member)


@api_bp.post("/auth/login")
def login():
    data = body()
    member = auth.find_member_by_token(str(data.get("token", "")))
    if member is None:
        raise Unauthorized("Ссылка недействительна")
    if not member.pin_is_set:
        raise DomainError("PIN ещё не задан — придумайте его", code="pin_not_set")
    if not auth.check_pin(member, str(data.get("pin", ""))):
        raise Unauthorized("Неверный PIN")
    return _login_response(member)


@api_bp.get("/join/status")
def join_status():
    """Можно ли сейчас вступить по этому коду — до того, как человек заполнит форму."""
    from flask import request

    settings = club.get_settings(db.session)
    db.session.commit()
    code = request.args.get("code", "")
    return jsonify(
        {
            "join_enabled": settings.join_enabled,
            "code_ok": club.code_matches(db.session, code) if code else False,
            "club_name": current_app.config["CLUB_NAME"],
        }
    )


@api_bp.post("/join")
def join():
    """Вступление по общему коду клуба: человек добавляет себя сам."""
    data = body()
    club.check_code(db.session, str(data.get("code", "")))

    name = club.normalize_name(str(data.get("full_name", "")))
    if club.name_taken(db.session, name) and not data.get("confirm_duplicate"):
        raise DomainError(
            f"Участник с именем «{name}» уже есть. Если это не вы — добавьте отчество "
            "или инициал. Если вы просто потеряли доступ, попросите администратора "
            "перевыпустить вашу ссылку.",
            code="name_taken",
        )

    pin = str(data.get("pin", ""))
    if pin != str(data.get("pin_repeat", pin)):
        raise DomainError("PIN и его повтор не совпали", code="pin_mismatch")
    auth.validate_pin_format(pin)

    raw, prefix, digest = auth.issue_token()
    member = club.create_self_joined_member(db.session, name, prefix, digest)
    auth.set_pin(member, pin)
    db.session.commit()

    # Личная ссылка нужна, чтобы зайти с другого устройства, когда cookie кончится
    return _login_response(member, {"link": auth.member_link(raw)})


@api_bp.post("/auth/logout")
def logout():
    """«Это не я / выйти» — cookie стирается."""
    response = make_response(jsonify({"ok": True}))
    return auth.clear_session_cookies(response)


def _login_response(member, extra: dict | None = None):
    session_token, csrf = auth.make_session_token(member)
    payload = {
        "member": _me_payload(member),
        # Для чат-бота и мобильного приложения: Authorization: Bearer <session_token>
        "session_token": session_token,
        "csrf_token": csrf,
    }
    payload.update(extra or {})
    response = make_response(jsonify(payload))
    return auth.apply_session_cookies(response, session_token, csrf)
