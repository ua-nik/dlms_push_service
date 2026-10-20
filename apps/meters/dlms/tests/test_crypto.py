import unittest
from django.test import override_settings
from apps.meters.dlms import RealDLMSDecoder

# Реальні зашифровані пакети NIK із тестової бази
REAL_PACKETS = [
    b"\x00\x01\x00\x01\x00\x01\x00F\xdb\x08/\x19\"\x91\x99\x16A\x03;0\x00\x00\x01\xe5\x02\\\xe9\xd2'\x1f\xd7\x8b\xe8\xc2\x04!\x1a\x91j\x9d\x7fX~\nz\x81L\xad\xea\x89\xe9Y?\x01\xf9.\xa8\xc0\x87\xb5\xbd\xfd\xef\xea\xb6\xbe\xcf(-\xfeI\xc0\x8f[\xe6\xdc\x84\x00",
    b'\x00\x01\x00\x01\x00\x01\x00F\xdb\x08/\x19"\x91\x99\x16A\x03;0\x00\x00\x01\xe6\x03\xd4\xd3W{\x7fd\x994\xe3\xb7\xc7\x19\xa3\xde5\x1a\xb2\x8cz\xc7\xb8\xa1\xe4D\xb8\x96\x91\xe9%\x91\xce\x1e\xb2\x82}\xf97\xa2\xe5@(\x0fb\x11\xf4\x93d\x80/\xa0\xf5\xc4\x13',
    b'\x00\x01\x00\x01\x00\x01\x00F\xdb\x08/\x19\"\x91\x99\x16A\x03;0\x00\x00\x01\xe7\x1c+\xbc?\xfb\x9aN9x\xf2k\xfa\xf5\xe9A\xe2i\xa2\xb6\x1dG\xb46\x1b/[\x1d"\xf5\xa0N\xffp\x8c\x9f\xfbI<@\x16:\x0e\x19x\xb7D\x9c\xec\x9c\xca\xe0\x8d\x19D',
    b'\x00\x01\x00\x01\x00\x01\x00F\xdb\x08/\x19\"\x91\x99\x16A\x03;0\x00\x00\x01\xe8\xb1\xf9[\xdd.\xdbA\xd3V\xdbW\xeeQ, \xc6\xeace:U\xbb\x18q~A\x9fE\xe8\xd3\xb4\xf3C)\xf4\xce\xb2\x1c\x81A\xa7\xe3\xcc\x00\xf0k~-\x98\xd7j\xf4\xb8\x06',
    b'\x00\x01\x00\x01\x00\x01\x00F\xdb\x08/\x19\"\x91\x99\x16A\x03;0\x00\x00\x01\xe9\xfd\x1c&\xa0\xa1\xa8\x8b\x86\xf3\xdc \x10\xb1{\xeb\xa3h\xa3\xb6\xd2\xad\x96SZ\xd4\x1f\x84\xd6\xcbi\xa86]\xb4\x1b\x8c\xac\xb5D\x94v\xc3\xf4 \xe1\x86\xffk\x1b`E\x11p\x08',
]


class DLMSCryptoTestCase(unittest.TestCase):
    """
    Тестування розшифрування реальних пакетів DLMS Push NIK.
    """

    def setUp(self):
        self.decoder = RealDLMSDecoder()

    def test_real_packet_decryption(self):
        """Перевірка успішного розшифрування реального пакета NIK."""
        packet = REAL_PACKETS[0]
        decoded = self.decoder.decode(packet, source_addr=("192.168.1.50", 4059))

        self.assertTrue(decoded.is_valid, f"Decoding failed: {decoded.error_message}")
        self.assertEqual(decoded.system_title, "2F19229199164103")
        self.assertEqual(decoded.invocation_counter, 485)
        self.assertIsNotNone(decoded.event_at)
        self.assertIn("parameters", decoded.parsed_payload)
        self.assertGreater(len(decoded.parsed_payload["parameters"]), 0)

        # Перевірка вилучених значень
        params = {p["name"]: p["value"] for p in decoded.parsed_payload["parameters"]}
        self.assertIn("Active Energy Positive (A+)", params)
        self.assertEqual(params["Active Energy Positive (A+)"], "73")

    def test_consecutive_invocation_counters(self):
        """Перевірка послідовних лічильників кадрів (Invocation Counter) у реальних пакетах."""
        expected_counters = [485, 486, 487, 488, 489]
        for pkt, expected_invoc in zip(REAL_PACKETS, expected_counters):
            decoded = self.decoder.decode(pkt)
            self.assertTrue(decoded.is_valid)
            self.assertEqual(decoded.invocation_counter, expected_invoc)

    def test_corrupted_packet_detection(self):
        """Перевірка виявлення пошкодження даних / помилки контрольної суми GCM."""
        valid_packet = bytearray(REAL_PACKETS[0])
        # Псуємо один байт у зашифрованих даних
        valid_packet[30] ^= 0xFF

        decoded = self.decoder.decode(bytes(valid_packet))
        self.assertFalse(decoded.is_valid)
        self.assertIn("InvalidTag", decoded.error_message or "")

    def test_truncated_packet(self):
        """Перевірка обробки вкороченого пакета."""
        truncated = REAL_PACKETS[0][:15]
        decoded = self.decoder.decode(truncated)
        self.assertFalse(decoded.is_valid)

    @override_settings(DLMS_ALLOW_UNENCRYPTED=True)
    def test_real_nik_hdlc_packet_decoding(self):
        """Перевірка розбору реального HDLC DataNotification пакета NIK (Template 11)."""
        hdlc_packet = bytes.fromhex(
            "7EA05D0502211345BDE6E7000FC00000010C07EA091E0310322626FF4C80"
            "0201093A0B10323330383231333035383035323032350000062300000459"
            "00000000000001AB000000000000018D000000000003A24D0000200C0100"
            "008EEA1B7E"
        )
        decoded = self.decoder.decode(hdlc_packet, source_addr=("172.25.0.1", 53525))

        self.assertTrue(decoded.is_valid, f"Decoding failed: {decoded.error_message}")
        self.assertEqual(decoded.system_title, "2308213058052025")
        self.assertEqual(decoded.serial_number, "2308213058052025")
        self.assertEqual(decoded.model_name, "NIK 2308")
        self.assertIsNotNone(decoded.event_at)
        self.assertEqual(decoded.event_at.year, 2026)
        self.assertEqual(decoded.event_at.month, 9)
        self.assertEqual(decoded.event_at.day, 30)

        # Перевірка розібраних параметрів
        params = {p["obis"]: p["value"] for p in decoded.parsed_payload["parameters"]}
        self.assertEqual(params["0.0.96.1.4.255"], "2308213058052025")
        self.assertEqual(params["1.0.1.8.0.255"], "1571")
        self.assertEqual(params["1.0.2.8.0.255"], "1113")
        self.assertEqual(params["1.0.31.7.0.255"], "0")
        self.assertEqual(params["1.0.32.7.0.255"], "427")
        self.assertEqual(params["1.0.51.7.0.255"], "0")
        self.assertEqual(params["1.0.52.7.0.255"], "397")
        self.assertEqual(params["1.0.71.7.0.255"], "0")
        self.assertEqual(params["1.0.72.7.0.255"], "238157")
        self.assertEqual(params["0.0.97.98.0.255"], "8204")
        self.assertEqual(params["0.0.97.98.1.255"], "16777358")
        for parameter in decoded.parsed_payload["parameters"]:
            self.assertNotIn("active_events", parameter)
            self.assertNotIn("unknown_bits", parameter)
            self.assertNotIn("alarm_register", parameter)
            self.assertNotIn("alarm_parse_error", parameter)
