"""Светлая и тёмная тема."""

from __future__ import annotations

import pathlib

from app.domain.levels import level_for, load_levels
from app.extensions import db

CSS = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "css" / "app.css"


def test_both_palettes_defined():
    """Основная тема тёмная («Хроно-Биом»), светлая — переопределение."""
    css = CSS.read_text(encoding="utf-8")
    assert ":root {" in css
    assert ':root[data-theme="light"] {' in css

    dark_block = css.split(":root {", 1)[1].split("}", 1)[0]
    light_block = css.split(':root[data-theme="light"] {', 1)[1].split("}", 1)[0]
    dark_vars = {line.split(":")[0].strip() for line in dark_block.splitlines()
                 if line.strip().startswith("--")}
    light_vars = {line.split(":")[0].strip() for line in light_block.splitlines()
                  if line.strip().startswith("--")}

    # Размеры, шрифты и тайминги переопределять незачем — только цвета
    not_colour = {"--radius", "--tap", "--font-body", "--font-display", "--font-num"}
    missing = (dark_vars - not_colour) - light_vars
    assert not missing, f"в светлой теме не переопределены: {sorted(missing)}"


def test_no_hardcoded_backgrounds_outside_palettes():
    """Жёсткий цвет фона вне блоков палитры не переживёт смену темы."""
    css = CSS.read_text(encoding="utf-8")
    body = css.split(':root[data-theme="light"] {', 1)[1].split("}", 1)[1]
    for bad in ("background: #fff;", "background: #ffffff;", "background: #f2efe7;",
                "background: #ece8de;", "background: #efece4;"):
        assert bad not in body, f"остался жёсткий цвет: {bad}"


def test_levels_carry_a_dark_colour(app):
    levels = load_levels(db.session)
    for level in levels:
        assert level.color_dark.startswith("#")
        # Наборы разные: пастельные цвета светлой темы на тёмном выцветают
        assert level.color_dark != level.color or level.idx == 0

    info = level_for(1000, levels)
    assert info.color == "#facc15"
    assert info.color_dark == "#e8c547"
    assert info.to_dict()["color_dark"] == "#e8c547"


def test_levels_api_exposes_both_colours(client, app):
    levels = client.get("/api/v1/levels").get_json()["levels"]
    assert len(levels) == 7
    assert all("color" in lvl and "color_dark" in lvl for lvl in levels)


def test_row_carries_both_level_colours(client, make_member, add_pages, weeks):
    actor = make_member("Цветной")
    add_pages(actor.id, 1000, weeks["this"])

    body = client.get("/board").get_data(as_text=True)
    assert "--level-color: #facc15" in body
    assert "--level-color-dark: #e8c547" in body


def test_toggle_and_antiflash_script_present(client, make_member):
    make_member("Кто-то")
    body = client.get("/").get_data(as_text=True)
    assert 'data-action="toggle-theme"' in body
    # Тема применяется до отрисовки, иначе тёмная моргнёт светлым
    assert "chitkod-theme" in body
    assert 'content="dark light"' in body
    assert body.index("chitkod-theme") < body.index("css/app.css")


def test_level_up_event_carries_dark_colour(client, make_member):
    actor = make_member("Растущий")
    client.post("/api/v1/entries", json={"pages": 100}, headers=actor.headers)
    payload = client.get("/api/v1/feed").get_json()["events"][0]["payload"]
    assert payload["color"] == "#f9a8d4"
    assert payload["color_dark"] == "#e39ac0"


def test_icons_replaced_emoji(client, make_member, add_pages, weeks):
    """В строке участника вместо эмодзи — свои SVG."""
    actor = make_member("Со значками")
    add_pages(actor.id, 300, weeks["this"])
    add_pages(actor.id, 200, weeks["prev"])

    body = client.get("/board").get_data(as_text=True)
    for emoji in ("📚", "🔥", "🏅", "🔒"):
        assert emoji not in body, f"остался эмодзи {emoji}"
    assert "<svg" in body


def test_numbers_use_tabular_font():
    css = CSS.read_text(encoding="utf-8")
    assert "--font-num" in css
    assert ".num, .joinlink__value" in css
    # Табличные цифры — иначе разряды прыгают при пересортировке строк
    assert css.count("font-variant-numeric: tabular-nums") >= 8


def test_fonts_linked_with_fallbacks(client, make_member):
    make_member("Кто-то")
    body = client.get("/").get_data(as_text=True)
    assert "fonts.googleapis.com" in body
    css = CSS.read_text(encoding="utf-8")
    # У каждой гарнитуры должен быть запасной стек: шрифты могут не загрузиться
    assert "--font-body: \"Golos Text\", system-ui" in css
    assert "--font-num: \"JetBrains Mono\", ui-monospace" in css
