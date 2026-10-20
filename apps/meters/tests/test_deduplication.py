from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest import skipUnless
from unittest.mock import Mock, patch

from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.meters.dlms import DecodedDLMSMessage
from apps.meters.models import DiagnosticMessage, Meter, MeterMessage
from apps.meters.services.message_processor import MessageProcessor


def processor(counter=10, title="TEST_METER", value="123"):
    return MessageProcessor(decoder=Mock(decode=Mock(return_value=DecodedDLMSMessage(
        system_title=title, invocation_counter=counter,
        parsed_payload={"parameters": [{"obis": "1.0.1.8.0.255", "value": value}]},
    ))))


class DeduplicationTests(TestCase):
    def test_repeat_keeps_original_and_does_not_publish_or_change_latest(self):
        service = processor()
        received = timezone.now()
        with patch.object(service, "_broadcast_events") as publish:
            with self.captureOnCommitCallbacks(execute=True):
                original = service.process_packet(b"packet", ("10.0.0.1", 4059), received)
            self.assertEqual(publish.call_count, 1)
            before = Meter.objects.get().last_seen_at
            with self.captureOnCommitCallbacks(execute=True):
                repeat = service.process_packet(b"packet", ("10.0.0.2", 5000), received + timedelta(hours=1))
            self.assertEqual(publish.call_count, 1)
        self.assertTrue(repeat["is_duplicate"])
        self.assertEqual(original["message_id"], repeat["message_id"])
        self.assertEqual(MeterMessage.objects.count(), 1)
        self.assertEqual(Meter.objects.get().last_seen_at, before)
        self.assertEqual(DiagnosticMessage.objects.count(), 0)

    def test_counter_conflict_is_not_saved_or_applied(self):
        service = processor()
        service.process_packet(b"packet")
        before = Meter.objects.get().last_seen_at
        with patch.object(service, "_broadcast_events") as publish:
            with self.captureOnCommitCallbacks(execute=True):
                result = service.process_packet(b"different-packet")
            publish.assert_not_called()
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(MeterMessage.objects.count(), 1)
        self.assertEqual(Meter.objects.get().last_seen_at, before)
        self.assertFalse(DiagnosticMessage.objects.exists())

    def test_equal_readings_with_new_counter_are_saved(self):
        processor(10).process_packet(b"packet-10")
        result = processor(11).process_packet(b"packet-11")
        self.assertFalse(result["is_duplicate"])
        self.assertEqual(MeterMessage.objects.count(), 2)

    def test_delayed_counter_is_not_treated_as_repeat(self):
        processor(11).process_packet(b"packet-11")
        result = processor(10).process_packet(b"packet-10")
        self.assertEqual(result["status"], "success")
        self.assertFalse(result["is_duplicate"])

    def test_packets_without_counter_are_not_silently_discarded(self):
        service = processor(None)
        service.process_packet(b"same-plaintext")
        result = service.process_packet(b"same-plaintext")
        self.assertFalse(result["is_duplicate"])
        self.assertEqual(MeterMessage.objects.filter(packet_digest__isnull=True).count(), 2)

    def test_deduplication_is_scoped_to_meter(self):
        processor(title="ONE").process_packet(b"packet")
        result = processor(title="TWO").process_packet(b"packet")
        self.assertFalse(result["is_duplicate"])
        self.assertEqual(MeterMessage.objects.count(), 2)

    def test_database_rejects_second_digest_for_same_meter(self):
        processor().process_packet(b"packet")
        original = MeterMessage.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            MeterMessage.objects.create(meter=original.meter, received_at=timezone.now(),
                                        packet_digest=original.packet_digest, raw_payload_hex="00")

    def test_repeat_lookup_does_not_load_historical_payloads(self):
        service = processor()
        service.process_packet(b"packet")
        with CaptureQueriesContext(connection) as queries:
            service.process_packet(b"packet")
        selects = [query["sql"] for query in queries if query["sql"].lstrip().upper().startswith("SELECT")]
        self.assertTrue(any("packet_digest" in sql for sql in selects))
        self.assertFalse(any("raw_payload_hex" in sql or "parsed_payload" in sql for sql in selects))



@skipUnless(connection.vendor == "postgresql", "Блокування рядків перевіряється на PostgreSQL")
class ParallelDeduplicationTests(TransactionTestCase):
    def test_simultaneous_conflicting_packets_do_not_overwrite_history(self):
        from threading import Barrier
        barrier = Barrier(2)
        Meter.objects.create(system_title="TEST_METER", last_seen_at=timezone.now())

        def ingest(raw):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return processor().process_packet(raw)
            finally:
                close_old_connections()

        with patch.object(MessageProcessor, "_broadcast_events") as publish:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(ingest, [b"one", b"two"]))
            self.assertEqual(publish.call_count, 1)
        self.assertEqual(sorted(result["status"] for result in results), ["conflict", "success"])
        self.assertEqual(MeterMessage.objects.count(), 1)
        self.assertEqual(DiagnosticMessage.objects.count(), 0)

    def test_simultaneous_first_delivery_creates_one_record_and_one_event(self):
        from threading import Barrier
        barrier = Barrier(2)

        def ingest():
            close_old_connections()
            try:
                service = processor()
                barrier.wait(timeout=10)
                return service.process_packet(b"same-packet")
            finally:
                close_old_connections()

        with patch.object(MessageProcessor, "_broadcast_events") as publish:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: ingest(), range(2)))
            self.assertEqual(publish.call_count, 1)
        self.assertEqual(MeterMessage.objects.count(), 1)
        self.assertEqual(Meter.objects.count(), 1)
        self.assertEqual({result["message_id"] for result in results}, {MeterMessage.objects.get().id})
        self.assertEqual(sorted(result["is_duplicate"] for result in results), [False, True])
