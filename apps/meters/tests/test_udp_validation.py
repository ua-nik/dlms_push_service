import asyncio
import json
import random
import socket
import struct

from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings

from apps.meters.models import DiagnosticMessage, Meter, MeterMessage
from apps.meters.services.udp_server import UDPServer


HEADER = bytes.fromhex("0F0000000100")
BODY = bytes([11, 16]) + b"2308213058052025" + struct.pack(">10I", *range(10))
STRAY = bytes.fromhex(
    "4B2E2F761B5549310F2C7409477B6278720E472508104A7E04795D7A2F2E637A4512"
    "7160673A11776605002E01622673716E19797E6377035C547D0C026006477277285A"
    "313951183F514640346C33255A4C1E598188"
)


@override_settings(DLMS_ALLOW_UNENCRYPTED=True, UDP_RECEIVER_HOST="127.0.0.1",
                   UDP_RECEIVER_PORT=0, UDP_RECEIVER_WORKERS=1,
                   USE_INMEMORY_CHANNEL_LAYER=True,
                   CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
class UDPValidationTests(TransactionTestCase):
    def test_malformed_datagrams_do_not_create_meters(self):
        rows = asyncio.run(self.exercise_receiver())
        # Machine-readable evidence includes every datagram actually received.
        print("UDP_VALIDATION_REPORT=" + json.dumps(rows))

    async def exercise_receiver(self):
        server = UDPServer()
        results = asyncio.Queue()
        loop = asyncio.get_running_loop()
        process = server.processor.process_packet

        def observe(packet, addr, received_at):
            try:
                result = process(packet, addr, received_at)
                counts = {
                    "meters": Meter.objects.count(),
                    "messages": MeterMessage.objects.count(),
                    "diagnostics": DiagnosticMessage.objects.count(),
                }
                loop.call_soon_threadsafe(results.put_nowait, (packet, result, counts, None))
            except Exception as error:
                loop.call_soon_threadsafe(results.put_nowait, (packet, None, None, error))
            finally:
                close_old_connections()

        server.processor.process_packet = observe
        task = asyncio.create_task(server.start())
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rows = []
        try:
            async def wait_ready():
                while server.transport is None:
                    if task.done():
                        await task
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(wait_ready(), 5)
            address = server.transport.get_extra_info("sockname")
            cases = [
                ("empty", b""), ("one_byte", b"\x00"),
                ("text", b"hello meter"), ("json", b'{"serial":"FAKE"}'),
                ("observed_stray_packet", STRAY),
                ("unknown_prefix_valid_apdu", b"INVALID!" + HEADER + BODY),
                ("wrong_wrapper_version", struct.pack(">4H", 2, 1, 1, len(HEADER + BODY)) + HEADER + BODY),
                ("wrong_wrapper_length", struct.pack(">4H", 1, 1, 1, 65535) + HEADER + BODY),
                ("unknown_template", HEADER + b"\x63\x01\x02\x03"),
                ("truncated_cipher", bytes.fromhex("DB082F19")),
                ("invalid_cipher_tag", bytes.fromhex("DB082F192291991641033000000001") + bytes(12)),
                ("trailing_garbage", HEADER + BODY + b"garbage"),
            ]
            cases += [(f"truncated_body_{n}", HEADER + BODY[:n]) for n in range(len(BODY))]
            rng = random.Random(20261020)
            cases += [(f"random_{n}", bytes(rng.randrange(256) for _ in range(n)))
                      for n in (2, 7, 8, 16, 32, 64, 128, 256, 1024)]
            valid = HEADER + BODY
            wrapper = struct.pack(">4H", 1, 1, 1, len(valid)) + valid
            cases.append(("positive_control_valid_wrapper", wrapper))
            for name, packet in cases:
                sender.sendto(packet, address)
                received, result, counts, error = await asyncio.wait_for(results.get(), 5)
                self.assertIsNone(error, str(error))
                self.assertEqual(received, packet)
                positive = name.startswith("positive_control")
                self.assertEqual(result["status"], "success" if positive else "invalid", name)
                self.assertEqual(counts, {"meters": int(positive), "messages": int(positive),
                                          "diagnostics": 0}, name)
                rows.append({"case": name, "bytes": len(packet), "hex": packet.hex().upper(),
                             "result": result, "database": counts})
            return rows
        finally:
            sender.close()
            await server.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
