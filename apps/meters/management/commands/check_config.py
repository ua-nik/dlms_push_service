import sys
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import connection
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from apps.meters.dlms import KeyResolver


class Command(BaseCommand):
    help = "Перевірка коректності конфігурації сервісу перед запуском."

    def handle(self, *args, **options):
        self.stdout.write("==================================================")
        self.stdout.write("Перевірка конфігурації NIK DLMS Push Service")
        self.stdout.write("==================================================")

        errors = []
        warnings = []

        # 1. Django Secret Key
        if settings.SECRET_KEY in ("insecure-default-change-in-production-random-key", ""):
            warnings.append("DJANGO_SECRET_KEY встановлено у значення за замовчуванням! Змініть його в .env для промислового середовища.")

        # 2. Database connection
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1;")
                row = cursor.fetchone()
                if row and row[0] == 1:
                    self.stdout.write(self.style.SUCCESS("[OK] База даних PostgreSQL доступна."))
                else:
                    errors.append("Неочікувана відповідь бази даних на SELECT 1.")
        except Exception as e:
            errors.append(f"Помилка підключення до бази даних: {e}")

        # 3. Redis / Channel Layer
        try:
            channel_layer = get_channel_layer()
            if channel_layer:
                self.stdout.write(self.style.SUCCESS(f"[OK] Channel Layer ініціалізовано ({channel_layer.__class__.__name__})."))
            else:
                warnings.append("Channel layer не налаштовано.")
        except Exception as e:
            warnings.append(f"Не вдалося підключитися до Channel Layer / Redis: {e}")

        # 4. DLMS Keys
        try:
            enc_key, auth_key = KeyResolver.get_keys_for_meter("DEFAULT")
            if len(enc_key) != 16:
                errors.append(f"DLMS_DEFAULT_GLOBAL_KEY повинен бути рівно 16 байт, наразі {len(enc_key)} байт.")
            if len(auth_key) != 16:
                errors.append(f"DLMS_DEFAULT_AUTH_KEY повинен бути рівно 16 байт, наразі {len(auth_key)} байт.")
            self.stdout.write(self.style.SUCCESS("[OK] Ключі шифрування DLMS валідні (AES-128 GCM)."))
        except Exception as e:
            errors.append(f"Помилка у форматі DLMS ключів: {e}")

        # 6. UDP Receiver port
        udp_port = getattr(settings, "UDP_RECEIVER_PORT", 4059)
        if not (1024 <= udp_port <= 65535):
            errors.append(f"Некоректний UDP_RECEIVER_PORT={udp_port}. Рекомендується порт від 1024 до 65535.")
        else:
            self.stdout.write(self.style.SUCCESS(f"[OK] Порт UDP-приймача: {udp_port}."))

        # Підсумки
        self.stdout.write("--------------------------------------------------")
        if warnings:
            for w in warnings:
                self.stdout.write(self.style.WARNING(f"[ПОПЕРЕДЖЕННЯ] {w}"))

        if errors:
            for err in errors:
                self.stdout.write(self.style.ERROR(f"[ПОМИЛКА] {err}"))
            self.stdout.write(self.style.ERROR("\nКонфігурація містить критичні помилки!"))
            sys.exit(1)
        else:
            self.stdout.write(self.style.SUCCESS("\nКонфігурацію перевірено успішно. Сервіс готовий до запуску."))
