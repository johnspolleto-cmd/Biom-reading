"""Светлая и тёмная тема."""

from __future__ import annotations

import pathlib

from app.domain.levels import level_for, load_levels
from app.extensions import db

CSS = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "css" / "app.css"


def test_both_palettes_defined():
    css = CSS.read_text(encoding="utf-8")
    assert ":root {" in css
    assert ':root[data-theme="dark"] {' in css

    # Каждая переменная светлой темы должна быть переопределена в тёмной,
    # иначе где-то останется светлый цвет на тёмном фоне
    light_block = css.split(":root {", 1)[1].split("}", 1)[0]
    dark_block = css.split(':root[data-theme="dark"] {', 1)[1].split("}", 1)[0]
    light_vars = {line.split(":")[0].strip() for line in light_block.splitlines()
                  if line.strip().startswith("--")}
    dark_vars = {line.split(":")[0].strip() for line in dark_block.splitlines()
                 if line.strip().startswith("--")}
    # Размеры и тайминги переопределять незачем — только цвета
    geometry = {"--radius", "--tap"}
    assert (light_vars - geometry) <= dark_vars


def test_no_hardcoded_white_backgrounds():
    """Захардкоженный белый фон в тёмной теме останется белым."""
    css = CSS.read_text(encoding="utf-8")
    body = css.split(':root[data-theme="dark"] {', 1)[1]
    for bad in ("background: #fff;", "background: #ffffff;", "background: #f2efe7;"):
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
    assert 'content="light dark"' in body
    assert body.index("chitkod-theme") < body.index("css/app.css")


def test_level_up_event_carries_dark_colour(client, make_member):
    actor = make_member("Растущий")
    client.post("/api/v1/entries", json={"pages": 100}, headers=actor.headers)
    payload = client.get("/api/v1/feed").get_json()["events"][0]["payload"]
    assert payload["color"] == "#f9a8d4"
    assert payload["color_dark"] == "#e39ac0"
