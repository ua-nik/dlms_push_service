#!/bin/sh
set -e

# Функція очікування доступності TCP-сервісу (PostgreSQL / Redis)
wait_for_service() {
    local host="$1"
    local port="$2"
    local name="$3"
    echo "Очікування готовності ${name} (${host}:${port})..."
    local counter=0
    until python -c "import socket; s = socket.socket(); s.settimeout(1.0); s.connect(('${host}', int(${port}))); s.close()" 2>/dev/null; do
        counter=$((counter + 1))
        if [ $counter -gt 60 ]; then
            echo "ПОМИЛКА: Перевищено таймаут очікування ${name} (${host}:${port})"
            exit 1
        fi
        sleep 1
    done
    echo "${name} готовий до прийому з'єднань."
}

# Очікуємо готовності PostgreSQL
if [ -n "$DB_HOST" ]; then
    wait_for_service "${DB_HOST}" "${DB_PORT:-5432}" "PostgreSQL"
fi

# Якщо налаштовано Redis, очікуємо готовності
if [ -n "$REDIS_HOST" ]; then
    wait_for_service "${REDIS_HOST}" "${REDIS_PORT:-6379}" "Redis"
fi

# Перевірка конфігурації
echo "Перевірка параметрів конфігурації..."
python manage.py check_config

# Залежно від аргументу запускаємо потрібний процес
case "$1" in
    api)
        echo "Застосування міграцій бази даних..."
        python manage.py migrate --noinput
        echo "Збір статичних файлів..."
        python manage.py collectstatic --noinput || true
        echo "Запуск ASGI веб-сервера Daphne (REST API & WebSocket)..."
        exec daphne -b 0.0.0.0 -p "${API_PORT:-8000}" config.asgi:application
        ;;
    udp_receiver)
        echo "Запуск незалежного процесу UDP-приймача..."
        exec python manage.py run_udp_receiver
        ;;
    *)
        exec "$@"
        ;;
esac
