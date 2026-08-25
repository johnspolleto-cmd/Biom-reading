"""Права: чужую строку не отредактировать прямым запросом к API, в обход интерфейса."""

from __future__ import annotations

from app.extensions import db
from app.models import Member


def test_guest_sees_board_but_cannot_write(client, make_member):
    make_member("Кто-то")
    assert client.get("/api/v1/leaderboard").status_code == 200
    assert client.get("/").status_code == 200
    assert client.post("/api/v1/entries", json={"pages": 10}).status_code == 401


def test_cannot_edit_foreign_entry(client, make_member):
    victim = make_member("Жертва")
    attacker = make_member("Нарушитель")

    created = client.post("/api/v1/entries", json={"pages": 50}, headers=victim.headers)
    entry_id = created.get_json()["entry"]["id"]

    response = client.patch(
        f"/api/v1/entries/{entry_id}", json={"pages": 9999}, headers=attacker.headers
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "forbidden"

    # Данные не изменились
    check = client.get(f"/api/v1/members/{victim.id}").get_json()
    assert check["total_pages"] == 50


def test_cannot_delete_foreign_entry(client, make_member):
    victim = make_member("Жертва")
    attacker = make_member("Нарушитель")
    created = client.post("/api/v1/entries", json={"pages": 70}, headers=victim.headers)
    entry_id = created.get_json()["entry"]["id"]

    assert client.delete(f"/api/v1/entries/{entry_id}", headers=attacker.headers).status_code == 403
    assert client.get(f"/api/v1/members/{victim.id}").get_json()["total_pages"] == 70


def test_cannot_write_entry_into_foreign_row(client, make_member):
    """Даже если подсунуть чужой member_id в теле — запись уйдёт в свою строку."""
    victim = make_member("Жертва")
    attacker = make_member("Нарушитель")

    client.post(
        "/api/v1/entries",
        json={"pages": 40, "member_id": victim.id},
        headers=attacker.headers,
    )
    assert client.get(f"/api/v1/members/{victim.id}").get_json()["total_pages"] == 0
    assert client.get(f"/api/v1/members/{attacker.id}").get_json()["total_pages"] == 40


def test_cannot_use_foreign_book(client, make_member, make_book):
    victim = make_member("Жертва")
    attacker = make_member("Нарушитель")
    book = make_book(victim.id, "Чужая книга")

    response = client.post(
        "/api/v1/entries", json={"pages": 10, "book_id": book.id}, headers=attacker.headers
    )
    assert response.status_code == 403


def test_cannot_finish_foreign_book(client, make_member, make_book):
    victim = make_member("Жертва")
    attacker = make_member("Нарушитель")
    book = make_book(victim.id)
    assert client.post(f"/api/v1/books/{book.id}/finish", headers=attacker.headers).status_code == 403


def test_cannot_rename_foreign_member(client, make_member):
    victim = make_member("Жертва")
    attacker = make_member("Нарушитель")
    client.patch("/api/v1/members/me", json={"full_name": "Взломано"}, headers=attacker.headers)
    assert db.session.get(Member, victim.id).full_name == "Жертва"


def test_admin_endpoints_closed_for_members(client, make_member):
    member = make_member("Обычный участник")
    assert client.get("/api/v1/admin/members", headers=member.headers).status_code == 403
    assert client.get("/api/v1/admin/export.zip", headers=member.headers).status_code == 403
    assert client.post("/api/v1/admin/challenges", json={}, headers=member.headers).status_code == 403


def test_admin_can_moderate(client, make_member):
    admin = make_member("Админ", admin=True)
    member = make_member("Участник")
    created = client.post("/api/v1/entries", json={"pages": 420}, headers=member.headers)
    entry_id = created.get_json()["entry"]["id"]

    flagged = client.get("/api/v1/admin/entries/flagged", headers=admin.headers).get_json()
    assert [e["id"] for e in flagged["entries"]] == [entry_id]

    assert client.post(
        f"/api/v1/admin/entries/{entry_id}/approve", headers=admin.headers
    ).status_code == 200
    assert client.get("/api/v1/admin/entries/flagged", headers=admin.headers).get_json()["entries"] == []


def test_cookie_write_requires_csrf(client, make_member):
    """Cookie-сессия без заголовка X-CSRF-Token писать не может."""
    actor = make_member("Кукисный")
    login = client.post("/api/v1/auth/login", json={"token": actor.raw_token, "pin": "2481"})
    csrf = login.get_json()["csrf_token"]

    # Cookie уже стоит у тест-клиента, но заголовка нет
    assert client.post("/api/v1/entries", json={"pages": 10}).status_code == 403
    # С заголовком — проходит
    assert client.post(
        "/api/v1/entries", json={"pages": 10}, headers={"X-CSRF-Token": csrf}
    ).status_code == 201


def test_logout_clears_session(client, make_member):
    actor = make_member("Выходящий")
    login = client.post("/api/v1/auth/login", json={"token": actor.raw_token, "pin": "2481"})
    csrf = login.get_json()["csrf_token"]
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert client.get("/api/v1/auth/me").get_json()["member"] is None


def test_reissued_link_revokes_old_sessions(client, make_member):
    admin = make_member("Админ", admin=True)
    member = make_member("Участник")
    assert client.get("/api/v1/auth/me", headers=member.headers).get_json()["member"] is not None

    client.post(f"/api/v1/admin/members/{member.id}/link", headers=admin.headers)
    assert client.get("/api/v1/auth/me", headers=member.headers).get_json()["member"] is None


def test_wrong_pin_rejected(client, make_member):
    actor = make_member("Забывчивый")
    assert client.post(
        "/api/v1/auth/login", json={"token": actor.raw_token, "pin": "0000"}
    ).status_code == 401


def test_bad_token_rejected(client):
    assert client.post(
        "/api/v1/auth/login", json={"token": "нет-такого", "pin": "1234"}
    ).status_code == 401
