"""Журнал чтения: суммирование, валидация, окно правки, проценты, дочитанная книга."""

from __future__ import annotations

from datetime import timedelta

from app.domain.time_utils import msk_today
from app.extensions import db
from app.models import ReadingEntry, utcnow


def test_entries_sum_not_overwrite(client, make_member):
    actor = make_member("Копилка")
    client.post("/api/v1/entries", json={"pages": 37}, headers=actor.headers)
    client.post("/api/v1/entries", json={"pages": 13}, headers=actor.headers)
    response = client.post("/api/v1/entries", json={"pages": 50}, headers=actor.headers)

    assert response.status_code == 201
    assert response.get_json()["row"]["total_pages"] == 100


def test_entry_rejects_zero_and_negative(client, make_member):
    actor = make_member("Нулевой")
    assert client.post("/api/v1/entries", json={"pages": 0}, headers=actor.headers).status_code == 400
    assert client.post("/api/v1/entries", json={"pages": -5}, headers=actor.headers).status_code == 400


def test_entry_over_300_is_saved_but_flagged(client, make_member):
    actor = make_member("Спринтер")
    response = client.post("/api/v1/entries", json={"pages": 301}, headers=actor.headers)

    assert response.status_code == 201
    entry = response.get_json()["entry"]
    assert entry["pages"] == 301
    assert entry["is_flagged"] is True
    # Записанное всё равно попадает в итог — админ разбирается постфактум
    assert response.get_json()["row"]["total_pages"] == 301


def test_entry_up_to_300_is_not_flagged(client, make_member):
    actor = make_member("Аккуратный")
    entry = client.post("/api/v1/entries", json={"pages": 300}, headers=actor.headers)
    assert entry.get_json()["entry"]["is_flagged"] is False


def test_absurd_number_rejected(client, make_member):
    actor = make_member("Опечатка")
    response = client.post("/api/v1/entries", json={"pages": 100000}, headers=actor.headers)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "pages_too_big"


def test_future_date_rejected(client, make_member):
    actor = make_member("Провидец")
    tomorrow = (msk_today() + timedelta(days=1)).isoformat()
    response = client.post(
        "/api/v1/entries", json={"pages": 10, "entry_date": tomorrow}, headers=actor.headers
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "future_date"


def test_percent_converts_by_book_volume(client, make_member, make_book):
    actor = make_member("Электронщик")
    book = make_book(actor.id, "Электронная", total_pages=400)

    response = client.post(
        "/api/v1/entries", json={"percent": 8, "book_id": book.id}, headers=actor.headers
    )
    entry = response.get_json()["entry"]
    assert entry["pages"] == 32  # 8 % от 400
    assert entry["input_kind"] == "percent"
    assert entry["input_value"] == 8


def test_percent_without_volume_uses_default(client, make_member, make_book):
    actor = make_member("Без объёма")
    book = make_book(actor.id, "Объём неизвестен", total_pages=None)
    response = client.post(
        "/api/v1/entries", json={"percent": 10, "book_id": book.id}, headers=actor.headers
    )
    assert response.get_json()["entry"]["pages"] == 30  # 10 % от условных 300


def test_percent_requires_book(client, make_member):
    actor = make_member("Без книги")
    response = client.post("/api/v1/entries", json={"percent": 10}, headers=actor.headers)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "percent_without_book"


def test_pages_and_percent_together_rejected(client, make_member, make_book):
    actor = make_member("Оба сразу")
    book = make_book(actor.id)
    response = client.post(
        "/api/v1/entries",
        json={"pages": 10, "percent": 5, "book_id": book.id},
        headers=actor.headers,
    )
    assert response.status_code == 400


def test_own_entry_editable_within_24h(client, make_member):
    actor = make_member("Исправляющий")
    created = client.post("/api/v1/entries", json={"pages": 40}, headers=actor.headers)
    entry_id = created.get_json()["entry"]["id"]

    response = client.patch(f"/api/v1/entries/{entry_id}", json={"pages": 45},
                            headers=actor.headers)
    assert response.status_code == 200
    assert response.get_json()["row"]["total_pages"] == 45


def test_own_entry_locked_after_24h(client, make_member):
    actor = make_member("Опоздавший")
    created = client.post("/api/v1/entries", json={"pages": 40}, headers=actor.headers)
    entry_id = created.get_json()["entry"]["id"]

    entry = db.session.get(ReadingEntry, entry_id)
    entry.created_at = utcnow() - timedelta(hours=25)
    db.session.commit()

    response = client.patch(f"/api/v1/entries/{entry_id}", json={"pages": 300},
                            headers=actor.headers)
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "edit_window_closed"


def test_admin_edits_old_entry(client, make_member):
    admin = make_member("Админ", admin=True)
    member = make_member("Участник")
    created = client.post("/api/v1/entries", json={"pages": 40}, headers=member.headers)
    entry_id = created.get_json()["entry"]["id"]

    entry = db.session.get(ReadingEntry, entry_id)
    entry.created_at = utcnow() - timedelta(days=5)
    db.session.commit()

    assert client.patch(
        f"/api/v1/entries/{entry_id}", json={"pages": 25}, headers=admin.headers
    ).status_code == 200


def test_deleted_entry_leaves_total(client, make_member):
    actor = make_member("Передумавший")
    created = client.post("/api/v1/entries", json={"pages": 80}, headers=actor.headers)
    client.post("/api/v1/entries", json={"pages": 20}, headers=actor.headers)
    entry_id = created.get_json()["entry"]["id"]

    response = client.delete(f"/api/v1/entries/{entry_id}", headers=actor.headers)
    assert response.get_json()["row"]["total_pages"] == 20
    # Мягкое удаление: строка в базе остаётся
    assert db.session.get(ReadingEntry, entry_id).deleted_at is not None


def test_finish_book_moves_to_shelf(client, make_member, make_book):
    actor = make_member("Дочитавший")
    book = make_book(actor.id, "Та самая")
    client.post("/api/v1/entries", json={"pages": 100, "book_id": book.id},
                headers=actor.headers)

    response = client.post(f"/api/v1/books/{book.id}/finish", headers=actor.headers)
    assert response.status_code == 200
    data = response.get_json()
    assert data["book"]["status"] == "finished"
    assert data["book"]["finished_at"] == msk_today().isoformat()
    # Счётчик книг +1, поле текущей книги очищено
    assert data["row"]["books_finished"] == 1
    assert data["row"]["current_book"] is None
    # Прочитанные страницы никуда не делись
    assert data["row"]["total_pages"] == 100


def test_finish_book_twice_rejected(client, make_member, make_book):
    actor = make_member("Дважды")
    book = make_book(actor.id)
    client.post(f"/api/v1/books/{book.id}/finish", headers=actor.headers)
    assert client.post(f"/api/v1/books/{book.id}/finish",
                       headers=actor.headers).status_code == 400


def test_quote_lands_on_the_wall(client, make_member, make_book):
    actor = make_member("Цитатчик")
    book = make_book(actor.id, "Щегол")

    response = client.post(
        "/api/v1/quotes",
        json={"text": "Красота ужасна.", "book_id": book.id, "page": 214},
        headers=actor.headers,
    )
    assert response.status_code == 201

    wall = client.get("/api/v1/quotes").get_json()["quotes"]
    assert len(wall) == 1
    assert wall[0]["member_name"] == "Цитатчик"
    assert wall[0]["book"] == "Автор — «Щегол»"
    assert wall[0]["page"] == 214

    row = client.get(f"/api/v1/members/{actor.id}").get_json()
    assert row["last_quote"]["text"] == "Красота ужасна."
    assert row["quotes_count"] == 1


def test_multiple_quotes_last_one_shown(client, make_member):
    actor = make_member("Многоцитатный")
    for i in range(3):
        client.post("/api/v1/quotes", json={"text": f"Цитата {i}", "book_label": "Книга"},
                    headers=actor.headers)
    row = client.get(f"/api/v1/members/{actor.id}").get_json()
    assert row["quotes_count"] == 3
    assert row["last_quote"]["text"] == "Цитата 2"
