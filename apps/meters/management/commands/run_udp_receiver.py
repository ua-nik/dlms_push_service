import asyncio
import logging
import signal
import sys
from django.core.management.base import BaseCommand
from apps.meters.services.udp_server import UDPServer

logger = logging.getLogger("apps.meters")


class Command(BaseCommand):
    help = "Запуск незалежного процесу UDP-приймача DLMS Push повідомлень."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Ініціалізація служби UDP-приймача..."))
        server = UDPServer()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Обробка сигналів зупинки
        def shutdown_handler():
            self.stdout.write(self.style.WARNING("\nОтримано сигнал завершення. Зупинка UDP-сервера..."))
            asyncio.create_task(server.stop())

        # На Unix системах реєструємо signal handlers
        if sys.platform != "win32":
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, shutdown_handler)

        try:
            loop.run_until_complete(server.start())
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nЗупинка за KeyboardInterrupt..."))
            loop.run_until_complete(server.stop())
        finally:
            loop.close()
            self.stdout.write(self.style.SUCCESS("Процес UDP-приймача коректно завершено."))
