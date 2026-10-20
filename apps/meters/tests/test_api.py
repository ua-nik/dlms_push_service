from datetime import datetime, timezone
from django.test import TestCase
from rest_framework.test import APIClient
from apps.meters.models import Meter, MeterMessage


class MeterAPITestCase(TestCase):
    """
    Тестування REST API сервісу.
    """

    def setUp(self):
        self.client = APIClient()
        self.meter = Meter.objects.create(
            system_title="2F19229199164103",
            serial_number="12345678",
            model_name="NIK 2308",
            last_seen_at=datetime(2026, 2, 1, 10, 0, 0, tzinfo=timezone.utc),
            last_ip="192.168.1.100",
            last_port=4059
        )
        self.msg1 = MeterMessage.objects.create(
            meter=self.meter,
            received_at=datetime(2026, 2, 1, 10, 0, 0, tzinfo=timezone.utc),
            raw_payload_hex="000102",
            parsed_payload={"parameters": [{"name": "Energy", "value": "100"}]},
            is_latest_2=True
        )
        self.msg2 = MeterMessage.objects.create(
            meter=self.meter,
            received_at=datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc),
            raw_payload_hex="000103",
            parsed_payload={"parameters": [{"name": "Energy", "value": "110"}]},
            is_latest_1=True
        )

    def test_meters_list(self):
        """Перевірка списку лічильників з пошуком та пагінацією."""
        response = self.client.get("/api/v1/meters/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("results", response.data)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["system_title"], "2F19229199164103")

    def test_meters_search(self):
        """Перевірка пошуку лічильника за серійним номером."""
        response = self.client.get("/api/v1/meters/?search=12345678")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)

        response_not_found = self.client.get("/api/v1/meters/?search=NONEXISTENT")
        self.assertEqual(len(response_not_found.data["results"]), 0)

    def test_meter_card(self):
        """Перевірка картки лічильника з двома останніми записами."""
        response = self.client.get(f"/api/v1/meters/{self.meter.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["system_title"], "2F19229199164103")
        self.assertIn("latest_records", response.data)
        self.assertEqual(len(response.data["latest_records"]), 2)

    def test_meter_latest(self):
        """Перевірка ендпоінта /latest/ для отримання рівно двох останніх записів."""
        response = self.client.get(f"/api/v1/meters/{self.meter.id}/latest/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)
        # Перший запис у відповіді має бути найсвіжішим (msg2)
        self.assertEqual(response.data[0]["id"], self.msg2.id)

    def test_meter_history_filter(self):
        """Перевірка фільтрації історії за діапазоном дат."""
        response = self.client.get(f"/api/v1/meters/{self.meter.id}/history/?from=2026-02-01T11:00:00Z")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["id"], self.msg2.id)

    def test_message_details(self):
        """Перевірка деталей конкретного повідомлення."""
        response = self.client.get(f"/api/v1/messages/{self.msg2.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["raw_payload_hex"], "000103")
        self.assertIn("parsed_payload", response.data)

    def test_health_check(self):
        """Перевірка ендпоінта готовності сервісу (/api/health/)."""
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "healthy")
        self.assertEqual(response.data["database"], "ok")

    def test_openapi_schema(self):
        """Перевірка доступності специфікації OpenAPI 3.0."""
        response = self.client.get("/api/schema/")
        self.assertEqual(response.status_code, 200)
        paths = response.data["paths"]
        self.assertIn("/api/v1/meters/", paths)
        self.assertNotIn("delete", paths["/api/v1/meters/{id}/"])
        self.assertIn("/api/v1/messages/", paths)
        self.assertIn("/api/health/", paths)
        self.assertNotIn("/api/v1/health/", paths)
        self.assertNotIn("/api/meters/", paths)
        self.assertNotIn("/api/messages/", paths)

    def test_diagnostic_register_value_is_returned_without_bit_decoding(self):
        self.msg2.parsed_payload = {"parameters": [{"obis": "0.0.97.98.0.255", "value": "8236"}]}
        self.msg2.save(update_fields=["parsed_payload"])
        response = self.client.get(f"/api/v1/messages/{self.msg2.pk}/")
        self.assertEqual(response.status_code, 200)
        parameter = response.data["parsed_payload"]["parameters"][0]
        self.assertEqual(parameter["value"], "8236")
        self.assertEqual(parameter, {"obis": "0.0.97.98.0.255", "value": "8236"})
        self.msg2.refresh_from_db()
        self.assertNotIn("active_events", self.msg2.parsed_payload["parameters"][0])
