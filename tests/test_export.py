"""Экспорт всех данных клуба в CSV."""

from __future__ import annotations

import io
import zipfile


def test_export_zip_contains_all_tables(client, make_member, make_book):
    admin = make_member("Админ", admin=True)
    member = make_member("Участник")
    book = make_book(member.id, "Книга для экспорта")
    client.post("/api/v1/entries", json={"pages": 42, "book_id": book.id},
                headers=member.headers)
    client.post("/api/v1/quotes", json={"text": "Цитата для экспорта", "book_id": book.id},
                headers=member.headers)

    response = client.get("/api/v1/admin/export.zip", headers=admin.headers)
    assert response.status_code == 200
    assert response.mimetype == "application/zip"

    archive = zipfile.ZipFile(io.BytesIO(response.data))
    assert set(archive.namelist()) == {
        "members.csv", "books.csv", "reading_entries.csv", "quotes.csv",
        "challenges.csv", "challenge_results.csv", "club_events.csv",
    }

    entries = archive.read("reading_entries.csv").decode("utf-8-sig")
    assert "Участник" in entries and "42" in entries

    quotes = archive.read("quotes.csv").decode("utf-8-sig")
    assert "Цитата для экспорта" in quotes

    # BOM на месте — Excel откроет кириллицу без плясок
    assert archive.read("members.csv").startswith("﻿".encode("utf-8"))
