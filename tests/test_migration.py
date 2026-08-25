"""Миграция и модели не должны разъезжаться.

Проверка нужна потому, что схему мы правим в двух местах: в моделях и в Alembic.
Тест прогоняет миграцию по-настоящему и сравнивает результат с metadata моделей.
"""

from __future__ import annotations

import pathlib

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.extensions import Base

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_migration_matches_models(tmp_path, monkeypatch):
    db_file = tmp_path / "migrated.sqlite3"
    url = f"sqlite+pysqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", url)

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")

    engine = sa.create_engine(url)
    inspector = sa.inspect(engine)

    migrated_tables = set(inspector.get_table_names()) - {"alembic_version"}
    model_tables = set(Base.metadata.tables)
    assert migrated_tables == model_tables

    for table in sorted(model_tables):
        migrated_columns = {col["name"] for col in inspector.get_columns(table)}
        model_columns = {col.name for col in Base.metadata.tables[table].columns}
        assert migrated_columns == model_columns, f"расходятся колонки таблицы {table}"

    # Уровни должны приехать вместе с миграцией
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("select name, threshold_pages from levels order by threshold_pages")
        ).all()
    assert [r[1] for r in rows] == [0, 100, 500, 1000, 2000, 5000, 10000]
    assert rows[3][0] == "Жёлтый рейнджер"

    engine.dispose()


def test_migration_downgrades_cleanly(tmp_path, monkeypatch):
    db_file = tmp_path / "roundtrip.sqlite3"
    url = f"sqlite+pysqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", url)

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = sa.create_engine(url)
    assert set(sa.inspect(engine).get_table_names()) <= {"alembic_version"}
    engine.dispose()
