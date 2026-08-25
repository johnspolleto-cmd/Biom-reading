#!/usr/bin/env bash
# Бэкап базы «ЧитКода». Запускать из корня проекта: ./scripts/backup.sh
# Кладёт сжатый дамп в ./backups и оставляет последние 14 штук.
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP="${BACKUP_KEEP:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"
FILE="${BACKUP_DIR}/chitkod-${STAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "[backup] снимаю дамп базы ${POSTGRES_DB:-chitkod}…"
docker compose exec -T db pg_dump \
	--username "${POSTGRES_USER:-chitkod}" \
	--dbname "${POSTGRES_DB:-chitkod}" \
	--clean --if-exists --no-owner \
	| gzip -9 > "$FILE"

SIZE="$(du -h "$FILE" | cut -f1)"
echo "[backup] готово: $FILE ($SIZE)"

# Чистим старые, оставляя последние $KEEP
ls -1t "${BACKUP_DIR}"/chitkod-*.sql.gz 2>/dev/null | tail -n "+$((KEEP + 1))" | while read -r old; do
	echo "[backup] удаляю старый: $old"
	rm -f "$old"
done

echo "[backup] в каталоге $(ls -1 "${BACKUP_DIR}"/chitkod-*.sql.gz 2>/dev/null | wc -l) файлов"
