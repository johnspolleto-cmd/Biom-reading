"""Русская типографика: склонения, «ёлочки», тире, неразрывные пробелы."""

from __future__ import annotations

import re

NBSP = " "
MDASH = "—"


def plural(n: int, one: str, few: str, many: str) -> str:
    """Правильная форма числительного: 1 страница, 2 страницы, 5 страниц."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def number(n: int | float) -> str:
    """10000 -> «10 000» с неразрывными пробелами."""
    return f"{int(n):,}".replace(",", NBSP)


def pages_word(n: int) -> str:
    return plural(n, "страница", "страницы", "страниц")


def pages(n: int) -> str:
    """«37 страниц» одним неразрывным куском — чтобы число не отрывалось от слова."""
    return f"{number(n)}{NBSP}{pages_word(n)}"


def books_word(n: int) -> str:
    return plural(n, "книга", "книги", "книг")


def books(n: int) -> str:
    return f"{number(n)}{NBSP}{books_word(n)}"


def weeks_word(n: int) -> str:
    return plural(n, "неделя", "недели", "недель")


def weeks(n: int) -> str:
    return f"{number(n)}{NBSP}{weeks_word(n)}"


def days_word(n: int) -> str:
    return plural(n, "день", "дня", "дней")


_QUOTE_OPEN = re.compile(r'(^|[\s([{<])"')
_QUOTE_CLOSE = re.compile(r'"')
_HYPHEN_DASH = re.compile(r"(\s)-(\s)")


def typo(text: str | None) -> str:
    """Кавычки-«ёлочки», тире вместо дефиса, неразрывный пробел перед тире."""
    if not text:
        return ""
    out = _QUOTE_OPEN.sub(lambda m: f"{m.group(1)}«", text)
    out = _QUOTE_CLOSE.sub("»", out)
    out = _HYPHEN_DASH.sub(lambda m: f"{NBSP}{MDASH} ", out)
    # Короткие слова не должны висеть в конце строки
    out = re.sub(r"(\s)(в|во|и|а|к|о|с|у|на|не|но|до|за|из|по|от|для)(\s)",
                 lambda m: f"{m.group(1)}{m.group(2)}{NBSP}", out, flags=re.IGNORECASE)
    return out


def moment(value, fmt: str = "%d.%m, %H:%M") -> str:
    """Момент времени по Москве. Принимает datetime или ISO-строку из API."""
    from datetime import datetime

    from .domain.time_utils import to_msk

    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return to_msk(value).strftime(fmt)


def register(app) -> None:
    """Подключить фильтры к Jinja."""
    app.jinja_env.filters.update(
        {
            "moment": moment,
            "pages": pages,
            "pages_word": pages_word,
            "books": books,
            "weeks": weeks,
            "days_word": days_word,
            "number": number,
            "typo": typo,
            "plural": plural,
        }
    )
    app.jinja_env.globals.update({"NBSP": NBSP, "MDASH": MDASH})
