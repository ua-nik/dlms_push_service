import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, Any

from django.db import transaction
from django.utils import timezone as django_tz
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from apps.core.consumers import EVENTS_GROUP_NAME
from apps.meters.models import Meter, MeterMessage
from apps.meters.dlms import RealDLMSDecoder, DecodedDLMSMessage, resolve_meter_model

logger = logging.getLogger(__name__)


class MessageProcessor:
    """
    Основний процесор вхідних повідомлень DLMS Push.
    
    1. Розшифровує та перевіряє пакет через декодер.
    2. Помилкові пакети лише журналює, без запису до бази.
    3. При успіху атомарно в транзакції:
       - Реєструє / оновлює лічильник;
       - Відсіює точні повтори; ізолює конфлікти Invocation Counter;
       - Зберігає повідомлення;
       - Відправляє WebSocket-подію після успішного commit.
    """

    def __init__(self, decoder=None):
        self.decoder = decoder or RealDLMSDecoder()

    def process_packet(
        self,
        raw_packet: bytes,
        source_addr: Optional[Tuple[str, int]] = None,
        received_at: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Обробляє один вхідний UDP пакет.
        """
        if received_at is None:
            received_at = django_tz.now()

        source_ip = source_addr[0] if source_addr else None
        source_port = source_addr[1] if source_addr else None

        # 1. Декодування та перевірка повідомлення
        try:
            decoded: DecodedDLMSMessage = self.decoder.decode(raw_packet, source_addr)
        except Exception as e:
            logger.exception(
                "Непередбачена помилка декодера при обробці повідомлення від %s:%s: %s | RAW HEX: %s",
                source_ip or "N/A",
                source_port or "N/A",
                e,
                raw_packet.hex().upper(),
            )
            return {"status": "error", "error": f"Виняток декодера: {e}"}

        # 2. Обробка помилкового повідомлення
        if not decoded.is_valid:
            logger.warning(
                "Помилка перевірки DLMS пакета від %s:%s (hint=%s): %s | RAW HEX: %s",
                source_ip or "N/A",
                source_port or "N/A",
                decoded.system_title,
                decoded.error_message,
                raw_packet.hex().upper(),
            )
            return {"status": "invalid", "error": decoded.error_message}

        # 3. Збереження валідного повідомлення в транзакції
        return self._save_valid_message(decoded, raw_packet, source_ip, source_port, received_at)

    @staticmethod
    def _format_payload_for_log(parsed_payload: Dict[str, Any]) -> str:
        """
        Форматує розібрані параметри повідомлення для виводу в лог.
        """
        if not parsed_payload:
            return "немає даних"

        parameters = parsed_payload.get("parameters")
        if isinstance(parameters, list) and parameters:
            parts = []
            for p in parameters:
                if isinstance(p, dict):
                    name = p.get("name") or p.get("obis") or "Параметр"
                    val = p.get("value", "")
                    unit = f" {p['unit']}" if p.get("unit") else ""
                    parts.append(f"{name}={val}{unit}")
                else:
                    parts.append(str(p))
            return "; ".join(parts)

        cleaned = {k: v for k, v in parsed_payload.items() if k not in ("raw_hex", "meta")}
        if cleaned:
            return str(cleaned)
        return "немає розібраних параметрів"

    def _save_valid_message(
        self,
        decoded: DecodedDLMSMessage,
        raw_packet: bytes,
        source_ip: Optional[str],
        source_port: Optional[int],
        received_at: datetime
    ) -> Dict[str, Any]:
        """
        Атомарно зберігає лічильник, повідомлення та публікує подію.
        """
        is_new_meter = False
        message = None
        meter = None
        # Без лічильника кадрів однаковий пакет може бути новим вимірюванням.
        packet_digest = hashlib.sha256(raw_packet).hexdigest() if decoded.invocation_counter is not None else None

        with transaction.atomic():
            # 1. Пошук або автоматична реєстрація лічильника
            meter_model = decoded.model_name or resolve_meter_model(decoded.serial_number or decoded.system_title)
            meter, created = Meter.objects.select_for_update().get_or_create(
                system_title=decoded.system_title,
                defaults={
                    "model_name": meter_model,
                    "serial_number": decoded.serial_number or "",
                    "last_seen_at": received_at,
                    "last_ip": source_ip,
                    "last_port": source_port,
                    "last_invocation_counter": decoded.invocation_counter,
                }
            )
            is_new_meter = created

            # Блокування Meter серіалізує перевірку та запис між UDP-воркерами.
            # Унікальний індекс додатково захищає від повторного запису пакета.
            if packet_digest is not None:
                existing_id = MeterMessage.objects.filter(
                    meter=meter, packet_digest=packet_digest
                ).values_list("id", flat=True).first()
                if existing_id is not None:
                    logger.info("Пропущено повтор пакета (system_title=%s, msg_id=%s)", meter.system_title, existing_id)
                    return {
                        "status": "success", "meter_id": meter.system_title,
                        "message_id": existing_id, "is_new_meter": False, "is_duplicate": True,
                    }

                if MeterMessage.objects.filter(
                    meter=meter, invocation_counter=decoded.invocation_counter
                ).exists():
                    reason = "Конфлікт Invocation Counter"
                    logger.warning(
                        "Конфлікт лічильника кадрів (system_title=%s, invoc=%s, source=%s:%s) | RAW HEX: %s",
                        meter.system_title, decoded.invocation_counter,
                        source_ip, source_port, raw_packet.hex().upper(),
                    )
                    return {"status": "conflict", "meter_id": meter.system_title, "error": reason}

            if not created:
                updated_meta = []
                if meter_model and (not meter.model_name or meter.model_name in ("NIK", "UNKNOWN")):
                    meter.model_name = meter_model
                    updated_meta.append("model_name")
                elif decoded.model_name and meter.model_name != decoded.model_name:
                    meter.model_name = decoded.model_name
                    updated_meta.append("model_name")
                if decoded.serial_number and not meter.serial_number:
                    meter.serial_number = decoded.serial_number
                    updated_meta.append("serial_number")
                if updated_meta:
                    meter.save(update_fields=updated_meta)

            # 3. Створення запису повідомлення
            message = MeterMessage.objects.create(
                meter=meter,
                received_at=received_at,
                event_at=decoded.event_at,
                invocation_counter=decoded.invocation_counter,
                raw_payload_hex=raw_packet.hex().upper(),
                packet_digest=packet_digest,
                parsed_payload=decoded.parsed_payload,
                source_ip=source_ip,
                source_port=source_port,
                is_duplicate=False,
            )

            # 4. Оновлення стану лічильника
            meter.last_seen_at = received_at
            meter.last_ip = source_ip
            meter.last_port = source_port
            if decoded.invocation_counter is not None:
                meter.last_invocation_counter = decoded.invocation_counter
            meter.save(update_fields=["last_seen_at", "last_ip", "last_port", "last_invocation_counter", "updated_at"])

            # 6. Відправка WebSocket-подій ПІСЛЯ фіксації транзакції (on_commit)
            transaction.on_commit(lambda: self._broadcast_events(meter, message, is_new_meter))

        # 7. Логування отриманого повідомлення від лічильника
        params_str = self._format_payload_for_log(decoded.parsed_payload)
        status_flag = " [новий лічильник]" if is_new_meter else ""
        logger.info(
            "Отримано повідомлення від лічильника %s%s (msg_id=%s, IP=%s:%s, invoc=%s, event_at=%s): %s | RAW HEX: %s",
            meter.system_title,
            status_flag,
            message.id,
            source_ip or "N/A",
            source_port or "N/A",
            decoded.invocation_counter if decoded.invocation_counter is not None else "N/A",
            decoded.event_at if decoded.event_at is not None else "N/A",
            params_str,
            message.raw_payload_hex,
        )

        return {
            "status": "success",
            "meter_id": meter.system_title,
            "message_id": message.id,
            "is_new_meter": is_new_meter,
            "is_duplicate": False,
        }

    def _broadcast_events(self, meter: Meter, message: MeterMessage, is_new_meter: bool) -> None:
        """
        Відправляє події підключеним WebSocket-клієнтам через Channel Layer.
        Помилка відправки не скасовує збереження в БД.
        """
        try:
            channel_layer = get_channel_layer()
            if channel_layer is None:
                return

            # Якщо зареєстровано новий лічильник - відправляємо подію появи
            if is_new_meter:
                meter_event = {
                    "event_type": "meter_created",
                    "schema_version": "1.0",
                    "meter_id": meter.system_title,
                    "timestamp": message.received_at.isoformat(),
                    "data": {
                        "id": meter.id,
                        "system_title": meter.system_title,
                        "model_name": meter.model_name,
                        "first_seen_at": meter.first_seen_at.isoformat(),
                    }
                }
                async_to_sync(channel_layer.group_send)(
                    EVENTS_GROUP_NAME,
                    {"type": "broadcast_event", "payload": meter_event}
                )

            # Подія нового повідомлення
            msg_event = {
                "event_type": "message_received",
                "schema_version": "1.0",
                "meter_id": meter.system_title,
                "message_id": message.id,
                "timestamp": message.received_at.isoformat(),
                "data": {
                    "message_id": message.id,
                    "received_at": message.received_at.isoformat(),
                    "event_at": message.event_at.isoformat() if message.event_at else None,
                    "invocation_counter": message.invocation_counter,
                    "parameters": message.parsed_payload.get("parameters", []),
                    "is_duplicate": message.is_duplicate,
                    "is_control_record": message.is_control_record,
                }
            }
            async_to_sync(channel_layer.group_send)(
                EVENTS_GROUP_NAME,
                {"type": "broadcast_event", "payload": msg_event}
            )

        except Exception as e:
            logger.warning("Помилка публікації WebSocket події: %s", e)
