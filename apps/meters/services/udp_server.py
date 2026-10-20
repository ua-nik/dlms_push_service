import asyncio
import logging
import socket
from datetime import datetime, timezone
from typing import Optional, Tuple
from django.conf import settings
from django.utils import timezone as django_tz

from .message_processor import MessageProcessor

logger = logging.getLogger(__name__)


class UDPProtocol(asyncio.DatagramProtocol):
    """
    Асинхронний протокол прийому вхідних датаграм UDP.
    Поміщає сирі пакети в обмежену чергу для асинхронної обробки воркерами.
    """

    def __init__(self, queue: asyncio.Queue, dropped_packets_counter: list):
        self.queue = queue
        self.dropped_packets_counter = dropped_packets_counter
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        recv_time = django_tz.now()
        logger.debug(
            "Отримано UDP датаграму від %s:%d (розмір: %d байт)",
            addr[0], addr[1], len(data)
        )
        try:
            self.queue.put_nowait((data, addr, recv_time))
        except asyncio.QueueFull:
            self.dropped_packets_counter[0] += 1
            if self.dropped_packets_counter[0] % 100 == 1:
                logger.error(
                    "Черга UDP-приймача переповнена! Відкинуто повідомлень: %d",
                    self.dropped_packets_counter[0]
                )

    def error_received(self, exc):
        logger.warning("Помилка сокета UDP: %s", exc)


class UDPServer:
    """
    Служба UDP-приймача DLMS Push повідомлень.
    Працює як окремий незалежний процес.
    """

    def __init__(self):
        self.host = getattr(settings, "UDP_RECEIVER_HOST", "0.0.0.0")
        self.port = getattr(settings, "UDP_RECEIVER_PORT", 4059)
        self.queue_size = getattr(settings, "UDP_RECEIVER_QUEUE_SIZE", 10000)
        self.worker_count = getattr(settings, "UDP_RECEIVER_WORKERS", 4)
        self.rcvbuf_bytes = getattr(settings, "UDP_SOCKET_RCVBUF_BYTES", 4194304)

        self.queue: asyncio.Queue = asyncio.Queue(maxsize=self.queue_size)
        self.dropped_packets = [0]
        self.is_running = False
        self.workers = []
        self.transport = None
        self.processor = MessageProcessor()

    async def _worker_loop(self, worker_id: int):
        """
        Цикл обробки пакетів із черги.
        """
        logger.info("Воркер #%d запущено", worker_id)
        while self.is_running or not self.queue.empty():
            try:
                item = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            data, addr, recv_time = item
            try:
                logger.debug(
                    "Воркер #%d: обробка пакета від %s:%s (%d байт)",
                    worker_id,
                    addr[0] if addr else "unknown",
                    addr[1] if addr else 0,
                    len(data)
                )
                # Викликаємо процесор повідомлень у пулі потоків Django (sync to async)
                await asyncio.to_thread(
                    self.processor.process_packet,
                    data,
                    addr,
                    recv_time
                )
            except Exception as e:
                logger.exception("Воркер #%d: помилка при обробці пакета від %s: %s", worker_id, addr, e)
            finally:
                self.queue.task_done()

        logger.info("Воркер #%d завершив роботу", worker_id)

    async def start(self):
        """
        Запускає UDP сервер та пул воркерів.
        """
        logger.info(
            "Запуск UDP-приймача на %s:%d (workers=%d, queue_size=%d)",
            self.host, self.port, self.worker_count, self.queue_size
        )
        self.is_running = True

        # Створюємо сокет зі збільшеним розміром буфера прийому
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.rcvbuf_bytes)
        except Exception as e:
            logger.warning("Не вдалося встановити SO_RCVBUF (%d байт): %s", self.rcvbuf_bytes, e)

        sock.bind((self.host, self.port))
        sock.setblocking(False)

        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(
            lambda: UDPProtocol(self.queue, self.dropped_packets),
            sock=sock
        )

        # Запускаємо воркери
        for i in range(self.worker_count):
            task = asyncio.create_task(self._worker_loop(i + 1))
            self.workers.append(task)

        logger.info("UDP-приймач успішно слухає порт %d/udp", self.port)

        try:
            # Очікуємо завершення
            while self.is_running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self):
        """
        Коректна зупинка сервера з обробкою пакетів, що залишилися в черзі.
        """
        if not self.is_running:
            return

        logger.info("Зупинка UDP-приймача: закриття сокета...")
        self.is_running = False

        if self.transport:
            self.transport.close()

        # Даємо воркерам час дообробити чергу (до 5 секунд)
        if not self.queue.empty():
            logger.info("Очікування обробки залишку пакетів у черзі (%d)...", self.queue.qsize())
            try:
                await asyncio.wait_for(self.queue.join(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Таймаут очікування черги при зупинці!")

        # Зупиняємо воркери
        for task in self.workers:
            task.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        logger.info("UDP-приймач повністю зупинено.")
