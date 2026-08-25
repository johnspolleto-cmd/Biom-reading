#!/bin/sh
set -e

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
	echo "[entrypoint] применяю миграции…"
	alembic upgrade head
	echo "[entrypoint] миграции применены"
fi

exec "$@"
