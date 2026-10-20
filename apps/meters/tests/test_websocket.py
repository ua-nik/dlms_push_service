from channels.testing import WebsocketCommunicator
from django.test import TestCase
from config.asgi import application
from apps.core.consumers import EVENTS_GROUP_NAME
from channels.layers import get_channel_layer


class WebSocketTestCase(TestCase):
    """
    Тестування WebSocket з'єднання та передачі подій клієнтам.
    """

    async def test_websocket_connection_and_heartbeat(self):
        communicator = WebsocketCommunicator(application, "/ws/events/")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # Перевіряємо вітальне повідомлення
        welcome = await communicator.receive_json_from()
        self.assertEqual(welcome["event_type"], "connected")
        self.assertEqual(welcome["schema_version"], "1.0")

        # Перевіряємо ping-pong heartbeat
        await communicator.send_json_to({"type": "ping", "data": {"echo": 123}})
        pong = await communicator.receive_json_from()
        self.assertEqual(pong["event_type"], "pong")
        self.assertEqual(pong["data"]["echo"], {"echo": 123})

        # Перевіряємо отримання широкомовного повідомлення групи
        channel_layer = get_channel_layer()
        test_event = {
            "event_type": "message_received",
            "schema_version": "1.0",
            "meter_id": "2F19229199164103",
            "message_id": 999,
            "timestamp": "2026-09-29T12:00:00Z",
            "data": {"energy": "12345"}
        }
        await channel_layer.group_send(
            EVENTS_GROUP_NAME,
            {"type": "broadcast_event", "payload": test_event}
        )

        received_event = await communicator.receive_json_from()
        self.assertEqual(received_event["event_type"], "message_received")
        self.assertEqual(received_event["meter_id"], "2F19229199164103")
        self.assertEqual(received_event["message_id"], 999)

        await communicator.disconnect()
