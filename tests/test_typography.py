"""Русская типографика в интерфейсе."""

from __future__ import annotations

from app.typography import NBSP, books, number, pages, pages_word, typo


def test_plural_forms():
    assert pages_word(1) == "страница"
    assert pages_word(2) == "страницы"
    assert pages_word(4) == "страницы"
    assert pages_word(5) == "страниц"
    assert pages_word(11) == "страниц"      # одиннадцать, а не «одиннадцать страница»
    assert pages_word(21) == "страница"
    assert pages_word(112) == "страниц"     # сто двенадцать страниц
    assert pages_word(114) == "страниц"
    assert pages_word(122) == "страницы"
    assert pages_word(115) == "страниц"
    assert pages_word(0) == "страниц"


def test_books_plural():
    assert books(1).endswith("книга")
    assert books(3).endswith("книги")
    assert books(7).endswith("книг")


def test_number_uses_nbsp():
    assert number(10000) == f"10{NBSP}000"
    assert number(999) == "999"


def test_pages_phrase_is_unbreakable():
    assert pages(37) == f"37{NBSP}страниц"
    assert pages(1) == f"1{NBSP}страница"


def test_quotes_and_dashes():
    assert typo('Книга "Щегол" хороша') == "Книга «Щегол» хороша"
    result = typo("Автор - это не профессия")
    assert "—" in result and " - " not in result
