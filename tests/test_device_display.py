"""Classic transport tests: real wire layouts and acknowledgements, no Qt."""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("device_display", Path(__file__).resolve().parents[1] / "src/app/utils/tempo_device_display.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeTransport:
    key, protocol = 1, "legacy_ec"

    def __init__(self):
        self.sent = []

    def send(self, command, payload=None):
        self.sent.append((command, payload))


class DisplayTests(unittest.TestCase):
    def setUp(self):
        self.time = 1.0
        self.transport = FakeTransport()
        self.settings = {"scene": "performance", "enabled": True}
        self.matrix = [[int(x == y) for x in range(256)] for y in range(32)]
        self.display = module.DeviceDisplay(lambda: self.transport, lambda _: self.matrix,
                                            lambda: "中文歌词", lambda *a, **k: None, lambda: self.time)
        self.display.tick(self.settings, auto_refresh=False)

    def ack(self, index, data, source=1):
        self.time += 0.01
        self.display.feed_report(index, data, source)
        self.display.tick(self.settings, auto_refresh=False)

    def start(self, scene="performance"):
        request = self.display.submit(scene, self.settings)
        self.display.tick(self.settings, auto_refresh=False)
        self.ack(0xEE, [0, 240, 180, 200, 0, 1, 0, 2, 255, 1, 0, 1])
        return request

    def image_ready(self):
        request = self.start()
        for _ in range(3):
            self.ack(0xEF, self.transport.sent[-1][1])
        self.ack(0xEE, [0, 240, 180, 200, 0, 1, 7, 1, 255, 0, 0, 1])
        self.ack(0x17, [0, 1, 0, 50])
        return request

    def finish_data(self):
        for packet in range(22):
            self.ack(0x17, [0, 3, packet >> 8, packet & 255])

    def verified(self):
        self.ack(0x17, [0, 5])
        self.ack(0xEE, [0, 240, 180, 200, 0, 1, 7, 1, 255, 0, 0, 1])

    def test_bitmap_round_trip_and_page_headers(self):
        data = module.encode_legacy_frame(self.matrix)
        self.assertEqual(len(data), 1064)
        pixels = bytearray()
        for page in range(8):
            record = data[page * 133:(page + 1) * 133]
            self.assertEqual(record[:5], bytes([7, 0, page, 0, 100]))
            pixels.extend(record[5:])
        restored = [[(pixels[(y // 8) * 256 + x] >> (y % 8)) & 1 for x in range(256)] for y in range(32)]
        self.assertEqual(restored, self.matrix)

    def test_image_requires_explicit_final_ack(self):
        request = self.image_ready()
        self.finish_data()
        self.assertFalse(request.done.is_set())
        self.assertEqual(self.transport.sent[-1], ("image", [0, 4]))
        chunks = [p for c, p in self.transport.sent if c == "image" and p[1] == 2]
        self.assertEqual([len(p) - 4 for p in chunks], [50] * 21 + [14])
        self.assertEqual(bytes(v for p in chunks for v in p[4:]), module.encode_legacy_frame(self.matrix))
        self.verified()
        self.assertTrue(request.done.is_set())
        self.assertTrue(request.result["transfer_verified"])
        self.assertTrue(request.result["verified"])

    def test_wrong_source_and_early_final_ack_do_not_advance(self):
        request = self.image_ready()
        count = len(self.transport.sent)
        self.ack(0x17, [0, 3, 0, 0], source=2)
        self.ack(0x17, [0, 5])
        self.assertEqual(len(self.transport.sent), count)
        self.assertFalse(request.done.is_set())

    def test_timeout_is_failure(self):
        request = self.image_ready()
        self.time += 1.3
        self.display.tick(self.settings, auto_refresh=False)
        self.assertTrue(request.done.is_set())
        self.assertIsNone(request.result)
        self.assertIn("未确认", request.error)

    def test_cursor_retries_are_bounded(self):
        request = self.image_ready()
        for _ in range(3):
            self.ack(0x17, [0, 6, 0, 0])
        self.assertIn("校验失败", request.error)

    def test_lyrics_use_source_14_and_preserve_rgb(self):
        request = self.start("lyrics")
        self.assertEqual(self.transport.sent[-1], ("screen", [1, 240, 180, 200, 0, 0, 1, 0, 1]))
        self.ack(0xEF, self.transport.sent[-1][1])
        self.ack(0xEE, [0, 240, 180, 200, 0, 1, 0, 2, 255, 1, 0, 1])
        data = "中文歌词".encode("utf-8")
        self.assertEqual(self.transport.sent[-1], ("text", [14, len(data), *data]))
        self.assertFalse(request.done.is_set())
        self.ack(0xE8, [1])
        self.assertTrue(request.result["verified"])

    def test_disconnect_completes_waiter_with_error(self):
        request = self.start()
        self.transport = None
        self.display.tick(self.settings, auto_refresh=False)
        self.assertTrue(request.done.is_set())
        self.assertFalse(self.display.snapshot()["verified"])

    def test_superseded_pending_request_finishes(self):
        first = self.display.submit("audio", self.settings)
        second = self.display.submit("lyrics", self.settings)
        self.assertTrue(first.done.is_set())
        self.assertIsNotNone(first.error)
        self.assertFalse(second.done.is_set())

    def test_identical_frame_completes_without_upload(self):
        self.image_ready()
        self.finish_data()
        self.verified()
        count = len(self.transport.sent)
        request = self.display.submit("performance", self.settings, force=False)
        self.display.tick(self.settings, auto_refresh=False)
        self.assertTrue(request.done.is_set())
        self.assertEqual(len(self.transport.sent), count)
        self.assertEqual(self.display.snapshot()["frames_completed"], 1)

    def test_a160_final_packet_can_ack_verified_directly(self):
        request = self.image_ready()
        for packet in range(21):
            self.ack(0x17, [0, 3, 0, packet])
        self.assertEqual(self.transport.sent[-2][1][2:4], [0, 21])
        self.assertEqual(self.transport.sent[-1], ("image", [0, 4]))
        self.ack(0x17, [0, 5])
        self.assertFalse(request.done.is_set())
        self.assertEqual(self.transport.sent[-1], ("query", None))
        self.ack(0xEE, [0, 240, 180, 200, 0, 1, 7, 1, 255, 0, 0, 1])
        self.assertTrue(request.result["transfer_verified"])
        self.assertTrue(request.result["verified"])

    def test_duplicate_chunk_ack_does_not_skip_data(self):
        self.image_ready()
        self.ack(0x17, [0, 3, 0, 0])
        count = len(self.transport.sent)
        self.ack(0x17, [0, 3, 0, 0])
        self.assertEqual(len(self.transport.sent), count)

    def test_external_scene_change_invalidates_display_confirmation(self):
        self.image_ready()
        self.finish_data()
        self.verified()
        self.assertTrue(self.display.snapshot()["verified"])
        self.ack(0xEE, [0, 240, 180, 200, 0, 1, 0, 2, 255, 0, 0, 1])
        self.assertFalse(self.display.snapshot()["verified"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
