"""Конфигурация приложения. Всё через переменные окружения — см. .env.example."""

from __future__ import annotations

import os
from datetime import timedelta


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-not-for-production")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://chitkod:chitkod@localhost:5432/chitkod"
    )
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # Из этого адреса собираются персональные ссылки участников
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/")

    # Сессия участника: cookie на 90 дней
    SESSION_COOKIE_NAME = "chitkod_session"
    SESSION_MAX_AGE = timedelta(days=90)
    COOKIE_SECURE = _bool("COOKIE_SECURE", PUBLIC_BASE_URL.startswith("https://"))

    # Правила журнала чтения
    ENTRY_PAGES_SOFT_MAX = 300  # больше — сохраняем, но помечаем для админа
    ENTRY_PAGES_HARD_MAX = 10_000  # больше — отказ, это заведомо опечатка
    ENTRY_EDIT_WINDOW = timedelta(hours=24)
    ENTRY_MAX_BACKDATE_DAYS = 30  # насколько назад можно поставить дату чтения

    # Условный объём книги, если он не указан, — для пересчёта процентов в страницы
    DEFAULT_BOOK_PAGES = 300

    # Защита четырёхзначного PIN от перебора
    PIN_MAX_ATTEMPTS = 5
    PIN_LOCKOUT = timedelta(minutes=15)

    CLUB_NAME = "БИОМ"
    APP_NAME = "ЧитКод"
    APP_TAGLINE = "Читай вместе с БИОМ"


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite+pysqlite:///:memory:"
    SECRET_KEY = "test-secret"
    PUBLIC_BASE_URL = "http://testserver"
    COOKIE_SECURE = False
