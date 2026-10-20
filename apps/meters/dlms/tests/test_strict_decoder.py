import struct
from django.test import TestCase, override_settings
from apps.meters.dlms import RealDLMSDecoder, CompactDataTemplateRegistry
from apps.meters.models import Meter, MeterMessage, DiagnosticMessage
from apps.meters.services.message_processor import MessageProcessor

HEADER = bytes.fromhex("0f0000000100")
BODY = bytes([11, 16]) + b"2308213058052025" + struct.pack(">10I", *range(10))

class StrictDecoderTests(TestCase):
    def setUp(self):
        self.decoder = RealDLMSDecoder()

    def test_template_rejects_every_truncated_prefix(self):
        template = CompactDataTemplateRegistry.get(11)
        for size in range(len(BODY)):
            with self.subTest(size=size), self.assertRaises(ValueError):
                template.decode_buffer(BODY[:size])
        self.assertEqual(len(template.decode_buffer(BODY)[0]), 11)
        with self.assertRaises(ValueError): template.decode_buffer(BODY + b"x")

    @override_settings(DLMS_ALLOW_UNENCRYPTED=False)
    def test_plaintext_disabled_even_when_well_formed(self):
        self.assertFalse(self.decoder.decode(HEADER + BODY).is_valid)

    @override_settings(DLMS_ALLOW_UNENCRYPTED=True)
    def test_plaintext_opt_in_has_explicit_authentication_metadata(self):
        result = self.decoder.decode(HEADER + BODY)
        self.assertTrue(result.is_valid)
        self.assertFalse(result.parsed_payload["meta"]["authenticated"])

    @override_settings(DLMS_ALLOW_UNENCRYPTED=True)
    def test_empty_unknown_and_truncated_packets_are_not_readings(self):
        packets = [b"", HEADER, HEADER + bytes([99, 1, 2, 3]),
                   HEADER + bytes([9]), HEADER + bytes([9, 0]),
                   HEADER + bytes([9, 0x80]), HEADER + bytes([9, 0x82, 1]),
                   HEADER + bytes([9, len(BODY) + 1]) + BODY,
                   HEADER + bytes([9, len(BODY) - 1]) + BODY,
                   HEADER + bytes([2, 1]), HEADER + bytes([2, 2]) + BODY]
        packets += [HEADER + BODY[:size] for size in range(len(BODY))]
        for packet in packets:
            with self.subTest(size=len(packet)):
                self.assertFalse(self.decoder.decode(packet).is_valid)

    @override_settings(DLMS_ALLOW_UNENCRYPTED=True)
    def test_octet_string_short_and_long_lengths(self):
        for prefix in (bytes([9, len(BODY)]), bytes([9, 0x81, len(BODY)]), bytes([2, 1, 9, len(BODY)])):
            self.assertTrue(self.decoder.decode(HEADER + prefix + BODY).is_valid)

    def test_wrapper_length_must_match(self):
        for length in (len(HEADER) - 1, len(HEADER) + 1):
            packet = struct.pack(">4H", 1, 1, 1, length) + HEADER
            self.assertFalse(self.decoder.decode(packet).is_valid)

    @override_settings(DLMS_ALLOW_UNENCRYPTED=True)
    def test_unknown_framing_is_rejected_even_with_valid_apdu_inside(self):
        packet = b"INVALID!" + HEADER + BODY
        result = self.decoder.decode(packet)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_message, "Unsupported transport framing")
        wrapper = struct.pack(">4H", 1, 1, 1, len(HEADER + BODY))
        self.assertTrue(self.decoder.decode(wrapper + HEADER + BODY).is_valid)

    @override_settings(DLMS_ALLOW_UNENCRYPTED=True)
    def test_observed_stray_packet_cannot_create_a_meter(self):
        packet = bytes.fromhex(
            "4B2E2F761B5549310F2C7409477B6278720E472508104A7E04795D7A2F2E637A4512"
            "7160673A11776605002E01622673716E19797E6377035C547D0C026006477277285A"
            "313951183F514640346C33255A4C1E598188"
        )
        with self.assertNumQueries(0):
            result = MessageProcessor().process_packet(packet, ("163.61.236.119", 4000))
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["error"], "Unsupported transport framing")
        self.assertFalse(Meter.objects.exists())
        self.assertFalse(MeterMessage.objects.exists())

    @override_settings(DLMS_ALLOW_UNENCRYPTED=True)
    def test_unknown_and_invalid_packets_are_not_saved(self):
        for packet in (HEADER + bytes([99, 1, 2, 3]), HEADER + BODY[:-1], HEADER):
            result = MessageProcessor().process_packet(packet, ("127.0.0.1", 4000))
            self.assertEqual(result["status"], "invalid")
        self.assertFalse(Meter.objects.exists())
        self.assertFalse(MeterMessage.objects.exists())
        self.assertEqual(DiagnosticMessage.objects.count(), 0)
