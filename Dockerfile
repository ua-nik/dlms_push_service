# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Змінні середовища Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on

# curl використовується перевіркою готовності API.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Створення непривілейованого користувача
RUN groupadd -r appgroup && useradd -r -g appgroup -d /app -s /sbin/nologin appuser

WORKDIR /app

# Установлення залежностей Python
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Копіювання вихідного коду застосунку
# Явний список файлів: робочі налаштування й сертифікати не потрапляють в образ.
COPY manage.py entrypoint.sh /app/
COPY apps/ /app/apps/
COPY config/ /app/config/
COPY scripts/ /app/scripts/

# Налаштування прав доступу до каталогу застосунку
RUN chown -R appuser:appgroup /app && chmod +x /app/entrypoint.sh

USER appuser

EXPOSE 8000 4059/udp

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["api"]
