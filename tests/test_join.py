"""Вступление в клуб по общему коду — без участия администратора."""

from __future__ import annotations

from app.domain import club
from app.extensions import db
from app.models import Member


def code(app) -> str:
    value = club.get_settings(db.session).join_code
    db.session.commit()
    return value


def test_anyone_with_the_code_can_join(client, app):
    response = client.post(
        "/api/v1/join",
        json={"code": code(app), "full_name": "Новый Читатель", "pin": "4726",
              "pin_repeat": "4726"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["member"]["full_name"] == "Новый Читатель"
    # Личная ссылка выдаётся сразу: без неё не зайти с другого устройства
    assert "/enter/" in data["link"]

    rows = client.get("/api/v1/leaderboard").get_json()["rows"]
    assert [r["full_name"] for r in rows] == ["Новый Читатель"]


def test_joined_member_can_write_immediately(client, app):
    joined = client.post(
        "/api/v1/join",
        json={"code": code(app), "full_name": "Сразу Пишущий", "pin": "1357",
              "pin_repeat": "1357"},
    ).get_json()
    headers = {"Authorization": "Bearer " + joined["session_token"]}

    added = client.post("/api/v1/entries", json={"pages": 40}, headers=headers)
    assert added.status_code == 201
    assert added.get_json()["row"]["total_pages"] == 40


def test_wrong_code_rejected(client, app):
    code(app)
    response = client.post(
        "/api/v1/join",
        json={"code": "WRONG123", "full_name": "Чужой", "pin": "1234", "pin_repeat": "1234"},
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "join_bad_code"
    assert client.get("/api/v1/leaderboard").get_json()["rows"] == []


def test_code_is_case_insensitive_and_trimmed(client, app):
    value = code(app)
    response = client.post(
        "/api/v1/join",
        json={"code": f"  {value.lower()} ", "full_name": "Небрежный Ввод", "pin": "8642",
              "pin_repeat": "8642"},
    )
    assert response.status_code == 200


def test_closed_intake_blocks_joining(client, app, make_member):
    admin = make_member("Админ", admin=True)
    value = code(app)

    assert client.patch(
        "/api/v1/admin/join-code", json={"enabled": "0"}, headers=admin.headers
    ).status_code == 200

    response = client.post(
        "/api/v1/join",
        json={"code": value, "full_name": "Опоздавший", "pin": "1122", "pin_repeat": "1122"},
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "join_disabled"


def test_rotating_code_invalidates_the_old_link(client, app, make_member):
    admin = make_member("Админ", admin=True)
    old = code(app)

    fresh = client.post("/api/v1/admin/join-code", headers=admin.headers).get_json()
    assert fresh["code"] != old

    assert client.post(
        "/api/v1/join",
        json={"code": old, "full_name": "По старой ссылке", "pin": "3344", "pin_repeat": "3344"},
    ).status_code == 403
    assert client.post(
        "/api/v1/join",
        json={"code": fresh["code"], "full_name": "По новой", "pin": "3344", "pin_repeat": "3344"},
    ).status_code == 200


def test_duplicate_name_warns_then_allows(client, app):
    value = code(app)
    first = {"code": value, "full_name": "Иван Петров", "pin": "5566", "pin_repeat": "5566"}
    assert client.post("/api/v1/join", json=first).status_code == 200

    again = client.post("/api/v1/join", json=first)
    assert again.status_code == 400
    assert again.get_json()["error"]["code"] == "name_taken"

    # Тёзка всё-таки может вступить, подтвердив, что это не ошибка
    assert client.post(
        "/api/v1/join", json={**first, "confirm_duplicate": True}
    ).status_code == 200


def test_pin_rules_apply_on_join(client, app):
    value = code(app)
    base = {"code": value, "full_name": "Слабый PIN"}

    mismatch = client.post("/api/v1/join", json={**base, "pin": "1234", "pin_repeat": "4321"})
    assert mismatch.get_json()["error"]["code"] == "pin_mismatch"

    short = client.post("/api/v1/join", json={**base, "pin": "12", "pin_repeat": "12"})
    assert short.get_json()["error"]["code"] == "pin_format"

    simple = client.post("/api/v1/join", json={**base, "pin": "7777", "pin_repeat": "7777"})
    assert simple.get_json()["error"]["code"] == "pin_too_simple"

    assert db.session.query(Member).count() == 0


def test_empty_name_rejected(client, app):
    response = client.post(
        "/api/v1/join",
        json={"code": code(app), "full_name": "  ", "pin": "2468", "pin_repeat": "2468"},
    )
    assert response.get_json()["error"]["code"] == "name_required"


def test_join_code_is_admin_only(client, app, make_member):
    member = make_member("Обычный")
    assert client.get("/api/v1/admin/join-code", headers=member.headers).status_code == 403
    assert client.post("/api/v1/admin/join-code", headers=member.headers).status_code == 403
    assert client.get("/api/v1/admin/join-code").status_code == 401


def test_self_joined_flag_visible_to_admin(client, app, make_member):
    admin = make_member("Админ", admin=True)
    client.post(
        "/api/v1/join",
        json={"code": code(app), "full_name": "Сам Пришёл", "pin": "9182", "pin_repeat": "9182"},
    )
    members = client.get("/api/v1/admin/members", headers=admin.headers).get_json()["members"]
    by_name = {m["full_name"]: m for m in members}
    assert by_name["Сам Пришёл"]["self_joined"] is True
    assert by_name["Админ"]["self_joined"] is False


def test_join_page_renders(client, app):
    value = code(app)
    assert client.get(f"/join/{value}").status_code == 200
    assert client.get("/join/").status_code == 200
    body = client.get(f"/join/{value}").get_data(as_text=True)
    # По верной ссылке код повторно не спрашиваем
    assert "join-name" in body and "join-pin" in body
