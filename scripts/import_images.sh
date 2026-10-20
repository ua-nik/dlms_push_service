#!/bin/bash
# ==============================================================================
# Імпорт Docker-образів на ізольованому сервері без Інтернету
# ==============================================================================
set -e

ARCHIVE_FILE="$1"

if [ -z "$ARCHIVE_FILE" ]; then
    ARCHIVE_FILE=$(ls -1 dlms_push_images_*.tar.gz 2>/dev/null | head -n 1 || true)
fi

if [ -z "$ARCHIVE_FILE" ] || [ ! -f "$ARCHIVE_FILE" ]; then
    echo "ПОМИЛКА: Вкажіть шлях до архіву образів: ./import_images.sh <path_to_images.tar.gz>"
    exit 1
fi

echo "Завантаження Docker-образів з архіву: ${ARCHIVE_FILE}..."
gunzip -c "$ARCHIVE_FILE" | docker load

echo "Образи успішно імпортовано до локального Docker registry."
echo "Тепер ви можете скопіювати .env.example в .env та запустити сервіс:"
echo "  cp .env.example .env"
echo "  docker compose up -d"
