#!/bin/bash
# ==============================================================================
# Відновлення бази даних PostgreSQL з резервної копії
# ==============================================================================
set -e

BACKUP_FILE="$1"

if [ -z "$BACKUP_FILE" ] || [ ! -f "$BACKUP_FILE" ]; then
    echo "ПОМИЛКА: Вкажіть шлях до файлу резервної копії: ./restore_db.sh <path_to_backup.sql.gz>"
    exit 1
fi

DB_CONTAINER="dlms_postgres"
DB_NAME="${DB_NAME:-dlms_push_db}"
DB_USER="${DB_USER:-dlms_user}"

echo "УВАГА: Усі поточні дані в ${DB_NAME} будуть перезаписані!"
read -p "Продовжити відновлення? (y/N): " -r CONFIRM
if [[ ! $CONFIRM =~ ^[Yy]$ ]]; then
    echo "Відновлення скасовано."
    exit 0
fi

echo "Відновлення даних з ${BACKUP_FILE} в ${DB_NAME}..."

gunzip -c "$BACKUP_FILE" | docker exec -i "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME"

echo "Базу даних успішно відновлено."
