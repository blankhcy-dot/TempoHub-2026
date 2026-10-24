"""Classic lyric transport tests with no Qt or hardware dependency."""

import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "device_display",
    Path(__file__).resolve().parents[1] / "src/app/utils/tempo_device_display.py",
)
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
        self.settings = {"scene": "lyrics", "enabled": True}
        self.display = module.DeviceDisplay(
            lambda: self.transport,
            lambda: "中文歌词",
            lambda *args, **kwargs: None,
            lambda: self.time,
        )
        self.display.tick(self.settings)

    def ack(self, index, data, source=1):
        self.time += 0.01
        self.display.feed_report(index, data, source)
        self.display.tick(self.settings)

    def start_lyrics(self):
        request = self.display.submit("lyrics", self.settings)
        self.display.tick(self.settings)
        self.ack(0xEE, [0, 240, 180, 200, 0, 1, 0, 2, 255, 1, 0, 1])
        return request

    def test_only_lyrics_scene_is_accepted(self):
        self.assertEqual(module.SCENES, ("lyrics",))
        with self.assertRaisesRegex(ValueError, "未知显示场景"):
            module.DisplayRequest("audio", {"enabled": True})

    def test_lyrics_wait_for_setting_ack_then_use_source_14(self):
        request = self.start_lyrics()
        self.assertEqual(
            self.transport.sent[-1],
            ("screen", [1, 240, 180, 200, 0, 0, 1, 0, 1]),
        )

        self.ack(0xEF, [1, 240, 180, 200, 0, 0, 1, 0, 1])
        self.assertEqual(self.transport.sent[-1], ("query", None))
        self.ack(0xEE, [0, 240, 180, 200, 0, 1, 0, 2, 255, 1, 0, 1])

        data = "中文歌词".encode("utf-8")
        self.assertEqual(self.transport.sent[-1], ("text", [14, len(data), *data]))
        self.assertFalse(request.done.is_set())
        self.ack(0xE8, [1])
        self.assertTrue(request.result["verified"])

    def test_timeout_finishes_request_with_error(self):
        request = self.start_lyrics()
        self.time += 4.0
        self.display.tick(self.settings)
        self.assertTrue(request.done.is_set())
        self.assertIsNone(request.result)
        self.assertIn("未确认", request.error)

    def test_disconnect_finishes_waiter(self):
        request = self.start_lyrics()
        self.transport = None
        self.display.tick(self.settings)
        self.assertTrue(request.done.is_set())
        self.assertFalse(self.display.snapshot()["verified"])

    def test_new_request_supersedes_pending_request(self):
        first = self.display.submit("lyrics", self.settings)
        second = self.display.submit("lyrics", self.settings)
        self.assertTrue(first.done.is_set())
        self.assertIsNotNone(first.error)
        self.assertFalse(second.done.is_set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
