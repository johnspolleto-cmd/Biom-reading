"""Сортировка, тай-брейк и мгновенный пересчёт после записи."""

from __future__ import annotations

from datetime import timedelta

from app.domain.leaderboard import build_rows
from app.extensions import db


def test_sorted_by_total_desc(app, make_member, add_pages, weeks):
    small = make_member("Маленький")
    big = make_member("Большой")
    middle = make_member("Средний")

    add_pages(small.id, 100, weeks["this"])
    add_pages(big.id, 900, weeks["this"])
    add_pages(middle.id, 500, weeks["this"])

    rows = build_rows(db.session)
    assert [row["full_name"] for row in rows] == ["Большой", "Средний", "Маленький"]
    assert [row["rank"] for row in rows] == [1, 2, 3]


def test_tie_broken_by_who_got_there_first(app, make_member, add_pages, weeks):
    """При равной сумме выше тот, кто достиг результата раньше."""
    early = make_member("Ранний")
    late = make_member("Поздний")

    add_pages(early.id, 300, weeks["prev"], hour=10)
    add_pages(late.id, 300, weeks["prev"], hour=22)

    rows = build_rows(db.session)
    assert [row["full_name"] for row in rows] == ["Ранний", "Поздний"]
    assert rows[0]["total_pages"] == rows[1]["total_pages"] == 300


def test_member_without_entries_goes_last(app, make_member, add_pages, weeks):
    reader = make_member("Читающий")
    make_member("Молчун")
    add_pages(reader.id, 10, weeks["this"])

    rows = build_rows(db.session)
    assert rows[-1]["full_name"] == "Молчун"
    assert rows[-1]["total_pages"] == 0
    assert rows[-1]["dynamics"]["kind"] == "pause"


def test_order_recalculated_immediately_after_entry(client, make_member, add_pages, weeks):
    leader = make_member("Лидер")
    chaser = make_member("Догоняющий")
    add_pages(leader.id, 200, weeks["prev"])
    add_pages(chaser.id, 150, weeks["prev"])

    before = client.get("/api/v1/leaderboard").get_json()["rows"]
    assert before[0]["full_name"] == "Лидер"

    response = client.post("/api/v1/entries", json={"pages": 100}, headers=chaser.headers)
    # Строка, вернувшаяся вместе с записью, уже знает новое место
    assert response.get_json()["row"]["rank"] == 1

    after = client.get("/api/v1/leaderboard").get_json()["rows"]
    assert [row["full_name"] for row in after] == ["Догоняющий", "Лидер"]


def test_inactive_member_hidden(app, make_member, add_pages, weeks):
    from app.models import Member

    active = make_member("Активный")
    gone = make_member("Ушедший")
    add_pages(active.id, 10, weeks["this"])
    add_pages(gone.id, 999, weeks["this"])

    db.session.get(Member, gone.id).is_active = False
    db.session.commit()

    assert [row["full_name"] for row in build_rows(db.session)] == ["Активный"]


def test_club_totals(client, make_member, add_pages, weeks):
    first = make_member("Первый")
    second = make_member("Второй")
    add_pages(first.id, 120, weeks["this"])
    add_pages(second.id, 80, weeks["prev"])

    club = client.get("/api/v1/stats").get_json()
    assert club["total_pages"] == 200
    assert club["week_pages"] == 120
    assert club["members"] == 2


def test_board_html_renders_rows(client, make_member, add_pages, weeks):
    actor = make_member("Виден в HTML")
    add_pages(actor.id, 640, weeks["this"] + timedelta(days=1))

    page = client.get("/board")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "Виден в HTML" in body
    assert 'data-row-id="%d"' % actor.id in body
    # Неразрывный пробел в числе и правильное числительное
    assert "640" in body and "страниц" in body
