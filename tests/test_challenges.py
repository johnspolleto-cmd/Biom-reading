"""Челленджи: автоматическая смена в понедельник, автозачёт, ручное подтверждение."""

from __future__ import annotations

from datetime import timedelta

from app.domain import challenges as ch
from app.extensions import db
from app.models import Challenge


def _make(week, title, kind, target=None, **kwargs):
    challenge = Challenge(week_start=week, title=title, kind=kind, target_value=target, **kwargs)
    db.session.add(challenge)
    db.session.commit()
    return challenge


def test_current_challenge_follows_the_week(app, weeks):
    """Смена челленджа не требует крона: он выбирается по неделе."""
    _make(weeks["prev"], "Прошлый", "pages_total", 100)
    _make(weeks["this"], "Этот", "pages_total", 500)
    _make(weeks["this"] + timedelta(days=7), "Следующий", "finish_book", 1)

    assert ch.current_challenge(db.session).title == "Этот"
    assert ch.challenge_for_week(db.session, weeks["prev"]).title == "Прошлый"
    # В понедельник текущим станет тот, что стоит в очереди
    assert ch.challenge_for_week(db.session, weeks["this"] + timedelta(days=7)).title == "Следующий"
    assert [c.title for c in ch.upcoming(db.session)] == ["Следующий"]


def test_no_challenge_for_free_week(app, weeks):
    assert ch.current_challenge(db.session) is None


def test_pages_challenge_counts_automatically(client, make_member, weeks):
    challenge = _make(weeks["this"], "500 страниц", "pages_total", 500)
    actor = make_member("Бегун")

    first = client.post("/api/v1/entries", json={"pages": 300}, headers=actor.headers)
    assert first.get_json()["challenge_done"] is False

    second = client.post("/api/v1/entries", json={"pages": 200}, headers=actor.headers)
    assert second.get_json()["challenge_done"] is True

    data = client.get("/api/v1/challenges/current").get_json()["challenge"]
    assert data["winners_count"] == 1
    assert data["winners"][0]["member_name"] == "Бегун"
    assert ch.progress_for(db.session, challenge, actor.id) == 500


def test_badge_appears_in_row(client, make_member, weeks):
    _make(weeks["this"], "100 страниц", "pages_total", 100)
    actor = make_member("Значкист")
    client.post("/api/v1/entries", json={"pages": 100}, headers=actor.headers)

    row = client.get(f"/api/v1/members/{actor.id}").get_json()
    assert len(row["badges"]) == 1
    assert row["badges"][0]["is_current"] is True


def test_badge_removed_when_entry_deleted(client, make_member, weeks):
    _make(weeks["this"], "100 страниц", "pages_total", 100)
    actor = make_member("Передумавший")
    created = client.post("/api/v1/entries", json={"pages": 100}, headers=actor.headers)
    assert created.get_json()["challenge_done"] is True

    client.delete(f"/api/v1/entries/{created.get_json()['entry']['id']}", headers=actor.headers)
    row = client.get(f"/api/v1/members/{actor.id}").get_json()
    assert row["badges"] == []


def test_days_streak_challenge(client, make_member, add_pages, weeks):
    challenge = _make(weeks["this"], "Пять дней подряд", "days_streak", 5)
    actor = make_member("Пятидневный")

    for day in range(4):
        add_pages(actor.id, 10, weeks["this"] + timedelta(days=day))
    ch.recompute(db.session, challenge)
    db.session.commit()
    assert ch.with_results(db.session, challenge)["winners_count"] == 0

    add_pages(actor.id, 10, weeks["this"] + timedelta(days=4))
    ch.recompute(db.session, challenge)
    db.session.commit()
    assert ch.with_results(db.session, challenge)["winners_count"] == 1


def test_finish_book_challenge(client, make_member, make_book, weeks):
    _make(weeks["this"], "Дочитать книгу", "finish_book", 1)
    actor = make_member("Финалист")
    book = make_book(actor.id, "Последняя глава")

    response = client.post(f"/api/v1/books/{book.id}/finish", headers=actor.headers)
    assert response.get_json()["challenge_done"] is True


def test_soft_challenge_needs_admin(client, make_member, weeks):
    challenge = _make(weeks["this"], "Что-нибудь про природу", "genre", genre="научпоп")
    admin = make_member("Админ", admin=True)
    actor = make_member("Участник")

    claimed = client.post(f"/api/v1/challenges/{challenge.id}/claim", headers=actor.headers)
    assert claimed.status_code == 200
    assert claimed.get_json()["result"]["status"] == "claimed"
    # Пока админ не подтвердил — не победитель
    assert client.get("/api/v1/challenges/current").get_json()["challenge"]["winners_count"] == 0

    pending = client.get("/api/v1/admin/challenges", headers=admin.headers).get_json()["pending"]
    assert len(pending) == 1

    client.post(f"/api/v1/admin/challenge-results/{pending[0]['id']}/confirm",
                json={"approve": "1"}, headers=admin.headers)
    assert client.get("/api/v1/challenges/current").get_json()["challenge"]["winners_count"] == 1


def test_auto_challenge_cannot_be_claimed(client, make_member, weeks):
    challenge = _make(weeks["this"], "500 страниц", "pages_total", 500)
    actor = make_member("Хитрец")
    response = client.post(f"/api/v1/challenges/{challenge.id}/claim", headers=actor.headers)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "challenge_is_auto"


def test_admin_queues_challenges_ahead(client, make_member, weeks):
    admin = make_member("Админ", admin=True)
    # Админ ввёл среду — неделя всё равно выровняется на понедельник
    wednesday = (weeks["this"] + timedelta(days=9)).isoformat()
    response = client.post(
        "/api/v1/admin/challenges",
        json={"week_start": wednesday, "title": "Через неделю", "type": "pages_total",
              "target_value": 300},
        headers=admin.headers,
    )
    assert response.status_code == 201
    assert response.get_json()["challenge"]["week_start"] == (
        weeks["this"] + timedelta(days=7)
    ).isoformat()


def test_one_challenge_per_week(client, make_member, weeks):
    admin = make_member("Админ", admin=True)
    payload = {"week_start": weeks["this"].isoformat(), "title": "Первый", "type": "pages_total",
               "target_value": 100}
    assert client.post("/api/v1/admin/challenges", json=payload,
                       headers=admin.headers).status_code == 201
    second = client.post("/api/v1/admin/challenges", json={**payload, "title": "Второй"},
                         headers=admin.headers)
    assert second.status_code == 400
    assert second.get_json()["error"]["code"] == "week_taken"


def test_archive_keeps_winners(client, make_member, add_pages, weeks):
    challenge = _make(weeks["prev"], "Прошлая неделя", "pages_total", 100)
    actor = make_member("Победитель")
    add_pages(actor.id, 150, weeks["prev"] + timedelta(days=2))
    ch.recompute(db.session, challenge)
    db.session.commit()

    archive = client.get("/api/v1/challenges").get_json()["archive"]
    assert archive[0]["title"] == "Прошлая неделя"
    assert archive[0]["winners"][0]["member_name"] == "Победитель"
