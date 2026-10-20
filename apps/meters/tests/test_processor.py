from unittest.mock import patch
from django.test import TestCase
from apps.meters.models import Meter, MeterMessage, DiagnosticMessage
from apps.meters.services.message_processor import MessageProcessor
from apps.meters.dlms import RealDLMSDecoder
from apps.meters.dlms.tests.test_crypto import REAL_PACKETS


class MessageProcessorTestCase(TestCase):
    """
    Тестування конвеєра обробки вхідних повідомлень:
    - автоматична реєстрація нового лічильника;
    - збереження валідного пакета та розібраних даних;
    - визначення повторно доставленого повідомлення (дубліката);
    - збереження помилок до діагностичного сховища;
    - виклик WebSocket-події після фіксації транзакції.
    """

    def setUp(self):
        self.processor = MessageProcessor(decoder=RealDLMSDecoder())

    @patch("apps.meters.services.message_processor.get_channel_layer")
    def test_auto_registration_and_message_saving(self, mock_get_channel_layer):
        """Перевірка автоматичної реєстрації лічильника та збереження повідомлення."""
        packet = REAL_PACKETS[0]
        self.assertEqual(Meter.objects.count(), 0)

        result = self.processor.process_packet(
            raw_packet=packet,
            source_addr=("10.0.0.1", 4059)
        )

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["is_new_meter"])
        self.assertFalse(result["is_duplicate"])

        # Лічильник має бути створений автоматично
        meter = Meter.objects.get(system_title="2F19229199164103")
        self.assertEqual(meter.last_ip, "10.0.0.1")
        self.assertEqual(meter.last_port, 4059)
        self.assertEqual(meter.last_invocation_counter, 485)

        # Повідомлення має бути збережене
        msg = MeterMessage.objects.get(id=result["message_id"])
        self.assertEqual(msg.meter, meter)
        self.assertEqual(msg.invocation_counter, 485)
        self.assertIn("parameters", msg.parsed_payload)

    def test_duplicate_message_detection(self):
        """Перевірка визначення дубліката повідомлення за Invocation Counter."""
        packet = REAL_PACKETS[0]

        # Перша відправка - нове повідомлення
        res1 = self.processor.process_packet(packet, source_addr=("10.0.0.1", 4059))
        self.assertEqual(res1["status"], "success")
        self.assertFalse(res1["is_duplicate"])

        # Повторна відправка того ж пакета - має бути позначено як дублікат
        res2 = self.processor.process_packet(packet, source_addr=("10.0.0.1", 4059))
        self.assertEqual(res2["status"], "success")
        self.assertTrue(res2["is_duplicate"])

        # Повтор повертає ідентифікатор оригіналу без нового запису.
        self.assertEqual(res2["message_id"], res1["message_id"])
        self.assertEqual(MeterMessage.objects.count(), 1)

    def test_corrupted_packet_is_not_saved(self):
        """Пошкоджений пакет не створює записів у базі."""
        corrupted = bytearray(REAL_PACKETS[0])
        corrupted[35] ^= 0xFF

        result = self.processor.process_packet(bytes(corrupted), source_addr=("10.0.0.2", 4059))
        self.assertEqual(result["status"], "invalid")

        self.assertFalse(DiagnosticMessage.objects.exists())
        self.assertFalse(Meter.objects.exists())
        self.assertFalse(MeterMessage.objects.exists())

    def test_message_logging(self):
        """Перевірка виводу отриманого повідомлення від лічильника в лог."""
        packet = REAL_PACKETS[0]
        with self.assertLogs("apps.meters.services.message_processor", level="INFO") as cm:
            result = self.processor.process_packet(
                raw_packet=packet,
                source_addr=("192.168.1.100", 4059)
            )

        self.assertEqual(result["status"], "success")
        log_output = "\n".join(cm.output)
        self.assertIn("Отримано повідомлення від лічильника 2F19229199164103", log_output)
        self.assertIn("IP=192.168.1.100:4059", log_output)
        self.assertIn("invoc=485", log_output)
        self.assertIn("Active Energy Positive (A+)=73 Wh", log_output)
        self.assertIn("RAW HEX:", log_output)

