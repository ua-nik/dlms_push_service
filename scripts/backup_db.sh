#!/bin/bash
# ==============================================================================
# Резервне копіювання бази даних PostgreSQL
# ==============================================================================
set -e

BACKUP_DIR="${1:-./backups}"
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/dlms_backup_${TIMESTAMP}.sql.gz"

DB_CONTAINER="dlms_postgres"
DB_NAME="${DB_NAME:-dlms_push_db}"
DB_USER="${DB_USER:-dlms_user}"

echo "Створення резервної копії бази даних ${DB_NAME} з контейнера ${DB_CONTAINER}..."

docker exec -t "$DB_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists | gzip > "$BACKUP_FILE"

echo "Резервну копію успішно створено: ${BACKUP_FILE} ($(du -h "$BACKUP_FILE" | cut -f1))"
