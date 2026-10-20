import logging
from datetime import datetime, timezone
from channels.generic.websocket import AsyncJsonWebsocketConsumer

logger = logging.getLogger(__name__)

EVENTS_GROUP_NAME = "dlms_meter_events"


class EventsConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer для передачі подій реального часу мобільним додаткам.
    
    Події:
    - meter_created: Зареєстровано новий лічильник
    - message_received: Отримано та збережено нове повідомлення від лічильника
    - pong: Відповідь на ping клієнта (heartbeat)
    """

    async def connect(self):
        await self.channel_layer.group_add(
            EVENTS_GROUP_NAME,
            self.channel_name
        )
        await self.accept()
        logger.info("WebSocket connected: %s", self.channel_name)

        # Відправляємо підтвердження успішного підключення
        await self.send_json({
            "event_type": "connected",
            "schema_version": "1.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "message": "NIK DLMS Push Service WebSocket connected"
            }
        })

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            EVENTS_GROUP_NAME,
            self.channel_name
        )
        logger.info("WebSocket disconnected: %s (code=%s)", self.channel_name, close_code)

    async def receive_json(self, content, **kwargs):
        """
        Обробка вхідних повідомлень від клієнта (наприклад, ping heartbeat).
        """
        msg_type = content.get("type") or content.get("event_type")
        if msg_type == "ping":
            await self.send_json({
                "event_type": "pong",
                "schema_version": "1.0",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": {"echo": content.get("data", {})}
            })

    async def broadcast_event(self, event):
        """
        Обробник подій, що надсилаються через channel_layer.group_send.
        event['payload'] містить структуру події.
        """
        payload = event.get("payload", {})
        await self.send_json(payload)
