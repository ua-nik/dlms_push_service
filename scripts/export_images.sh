#!/bin/bash
# ==============================================================================
# Експорт Docker-образів для автономного встановлення без доступу до Інтернету
# ==============================================================================
set -euo pipefail

OUTPUT_DIR="${1:-./offline_bundle}"
if [ -e "$OUTPUT_DIR" ]; then
    echo "ПОМИЛКА: Каталог призначення вже існує. Вкажіть новий каталог, щоб не включити старі файли або секрети."
    exit 1
fi
mkdir -p "$OUTPUT_DIR"

ARCHIVE_NAME="${OUTPUT_DIR}/dlms_push_images_$(date +%Y%m%d).tar.gz"

echo "1. Збирання локальних образів сервісу..."
docker compose build

echo "2. Вивантаження всіх використовуваних образів в архів: ${ARCHIVE_NAME}..."
docker save \
    postgres:16-alpine \
    redis:7-alpine \
    nginx:alpine \
    dlms_push_service-api:latest \
    dlms_push_service-udp_receiver:latest \
    | gzip > "$ARCHIVE_NAME"

echo "3. Копіювання конфігураційних файлів до ${OUTPUT_DIR}..."
cp docker-compose.yml "$OUTPUT_DIR/"
cp .env.example "$OUTPUT_DIR/"
# Копіюємо лише конфігурацію: сертифікати та приватні ключі залишаються на сервері.
mkdir -p "$OUTPUT_DIR/nginx"
cp nginx/nginx.conf "$OUTPUT_DIR/nginx/"
cp -r scripts "$OUTPUT_DIR/"
cp README.md "$OUTPUT_DIR/"

echo "=================================================="
echo "Комплект для автономного встановлення готовий у: ${OUTPUT_DIR}"
echo "Розмір архіву образів: $(du -h "$ARCHIVE_NAME" | cut -f1)"
echo "Перенесіть директорію ${OUTPUT_DIR} на цільовий сервер і виконайте scripts/import_images.sh"
echo "=================================================="
