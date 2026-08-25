#!/usr/bin/env bash
# Восстановление из бэкапа: ./scripts/restore.sh backups/chitkod-20260825-120000.sql.gz
# ВНИМАНИЕ: текущие данные будут заменены содержимым дампа.
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

FILE="${1:-}"
if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
	echo "Укажите файл бэкапа. Доступные:"
	ls -1t ./backups/chitkod-*.sql.gz 2>/dev/null || echo "  (бэкапов нет)"
	exit 1
fi

read -r -p "Заменить текущую базу содержимым $FILE? Введите «да»: " answer
[ "$answer" = "да" ] || { echo "Отменено."; exit 1; }

echo "[restore] разворачиваю $FILE…"
gunzip -c "$FILE" | docker compose exec -T db psql \
	--username "${POSTGRES_USER:-chitkod}" \
	--dbname "${POSTGRES_DB:-chitkod}" \
	--quiet

echo "[restore] готово. Перезапустите приложение: docker compose restart web worker"
