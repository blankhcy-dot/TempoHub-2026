"""Acknowledged native-lyrics transport for the classic Halo PixelBar protocol.

The host calls tick() on its device/GUI thread; the HID reader only queues
normalized reports through feed_report().
"""

from __future__ import annotations

import threading
import time
from collections import deque


SCREEN_QUERY, SCREEN_SET, TEXT_SET = 0xEE, 0xEF, 0xE8
SCENES = ("lyrics",)


def parse_legacy_screen(payload):
    if len(payload) < 12:
        return None
    return {
        "rgb": list(payload[1:4]),
        "group": payload[4],
        "mode": payload[5],
        "option0": payload[6],
        "option1": payload[7],
        "option2": payload[8],
        "music_enabled": payload[9],
        "music_kind": payload[10],
        "lyric_mode": payload[11],
    }


class DisplayRequest:
    def __init__(self, scene, settings, force=True):
        if scene not in SCENES:
            raise ValueError("未知显示场景")
        self.scene = scene
        self.settings = dict(settings)
        self.force = bool(force)
        self.done = threading.Event()
        self.result = None
        self.error = None


class DeviceDisplay:
    """Apply and verify the firmware-native lyric screen."""

    def __init__(self, transport_provider, text_provider, log, clock=time.monotonic):
        self.transport_provider = transport_provider
        self.text_provider = text_provider
        self.log = log
        self.clock = clock
        self._lock = threading.RLock()
        self._reports = deque(maxlen=64)
        self._pending = None
        self._active = None
        self._transport = None
        self._transport_key = None
        self._native = None
        self._phase = "idle"
        self._sent_at = 0.0
        self._phase_deadline = 0.0
        self._expected_setting_acks = 0
        self._setting_acks = 0
        self._started_at = 0.0
        self._deadline = 0.0
        self._displayed_scene = None
        self._configuration = None
        self._last_error = None
        self._last_latency_ms = None
        self._next_status_query = 0.0

    def submit(self, scene, settings, force=True):
        request = DisplayRequest(scene, settings, force)
        with self._lock:
            if self._pending is not None:
                self._pending.error = "显示请求已被更新的选择替代"
                self._pending.done.set()
            self._pending = request
        return request

    def feed_report(self, index, payload, source=None):
        if index not in (SCREEN_QUERY, SCREEN_SET, TEXT_SET):
            return
        with self._lock:
            self._reports.append(
                (self.clock(), int(index), list(payload or []), source)
            )

    def snapshot(self):
        with self._lock:
            native = dict(self._native or {})
            return {
                "connected": self._transport is not None,
                "protocol": "legacy_ec" if self._transport is not None else None,
                "phase": self._phase,
                "pending": self._active is not None or self._pending is not None,
                "applying": bool(
                    self._active
                    and not self._active.done.is_set()
                ),
                "scene": self._displayed_scene,
                "verified": (
                    self._displayed_scene == "lyrics"
                    and self._last_error is None
                    and self._home_matches("lyrics")
                ),
                "transfer_verified": (
                    self._displayed_scene == "lyrics"
                    and self._last_error is None
                ),
                "last_error": self._last_error,
                "last_latency_ms": self._last_latency_ms,
                "native": native,
                "lyrics": {
                    "mode_group_index": native.get("group"),
                    "is_lyric_enabled": (
                        native.get("music_enabled") == 1
                        and native.get("music_kind") == 0
                    ),
                    "lyrics_display_mode": native.get("lyric_mode"),
                },
            }

    def tick(self, settings):
        with self._lock:
            now = self.clock()
            try:
                transport = self.transport_provider()
                if transport is None:
                    raise RuntimeError("音响未连接，请检查 USB 数据线")
                if transport.protocol != "legacy_ec":
                    raise RuntimeError("此设备的显示协议尚未验证")
                if transport.key != self._transport_key:
                    self._transport_key = transport.key
                    self._native = None
                    self._displayed_scene = None
                    self._configuration = None
                    self._last_error = None
                    self._reports.clear()
                    if self._active:
                        self._fail("音响连接已变化，请重新应用歌词")
                self._transport = transport
            except Exception as error:
                self._transport = None
                self._transport_key = None
                self._native = None
                self._displayed_scene = None
                if self._active or self._pending:
                    self._fail(str(error), include_pending=True)
                self._last_error = str(error)
                return

            reports = list(self._reports)
            self._reports.clear()
            for stamp, index, payload, source in reports:
                if source is not None and source != self._transport_key:
                    continue
                if index == SCREEN_QUERY:
                    native = parse_legacy_screen(payload)
                    if native:
                        self._native = native
                if self._active and stamp >= self._sent_at:
                    self._receive(index, payload)

            if self._active:
                if now >= self._deadline or now >= self._phase_deadline:
                    self._fail("音响未确认显示，请检查连接后重新应用")
                return

            if not settings.get("enabled", True):
                if self._pending:
                    self._pending.error = "插件已暂停显示"
                    self._pending.done.set()
                    self._pending = None
                self._displayed_scene = None
                return

            request = self._pending
            self._pending = None
            if request is None:
                if now >= self._next_status_query:
                    try:
                        self._transport.send("query")
                    except Exception as error:
                        self._fail(str(error))
                    self._next_status_query = now + 2.0
                return
            self._start(request)

    def _send(self, command, payload=None, phase=None, timeout=1.2):
        self._sent_at = self.clock()
        self._phase_deadline = self._sent_at + timeout
        if phase:
            self._phase = phase
        self._transport.send(command, payload)

    def _start(self, request):
        self._active = request
        self._started_at = self.clock()
        self._deadline = self._started_at + 9.0
        self._last_error = None
        try:
            if self._native is None:
                self._send("query", phase="initial_query", timeout=3.0)
            else:
                self._prepare()
        except Exception as error:
            self._fail(str(error))

    def _prepare(self):
        native = self._native
        rgb = native["rgb"]
        group = native["group"]
        mode = int(self._active.settings.get("lyrics_display_mode", 1) or 1)
        self._expected_setting_acks = 1
        self._setting_acks = 0
        self._sent_at = self.clock()
        self._phase_deadline = self._sent_at + 3.5
        self._phase = "await_settings"
        self._transport.send("screen", [1, *rgb, group, 0, 1, 0, mode])

    def _receive(self, index, payload):
        try:
            if self._phase == "initial_query" and index == SCREEN_QUERY and self._native:
                self._prepare()
            elif self._phase == "await_settings" and index == SCREEN_SET:
                self._setting_acks += 1
                if self._setting_acks >= self._expected_setting_acks:
                    self._send("query", phase="verify_home", timeout=3.0)
            elif self._phase == "verify_home" and index == SCREEN_QUERY:
                if not self._home_matches():
                    self._fail("音响未切换到歌词显示")
                    return
                text = str(self.text_provider() or "等待播放音乐")
                data = (
                    text.encode("utf-8")[:55]
                    .decode("utf-8", "ignore")
                    .encode("utf-8")
                )
                self._send("text", [14, len(data), *data], "lyric_text")
            elif self._phase == "lyric_text" and index == TEXT_SET:
                if payload and payload[0] == 1:
                    self._complete()
                else:
                    self._fail("音响未接受当前歌词")
        except Exception as error:
            self._fail(str(error))

    def _home_matches(self, scene="lyrics"):
        native = self._native or {}
        return (
            scene == "lyrics"
            and native.get("music_enabled") == 1
            and native.get("music_kind") == 0
        )

    def _complete(self):
        request = self._active
        self._displayed_scene = request.scene
        self._configuration = self._settings_key(request.scene, request.settings)
        self._last_error = None
        completed_at = self.clock()
        request_latency_ms = round((completed_at - self._started_at) * 1000, 2)
        self._last_latency_ms = request_latency_ms
        request.result = {
            "scene": request.scene,
            "verified": True,
            "transfer_verified": True,
            "protocol": "legacy_ec",
            "latency_ms": request_latency_ms,
        }
        request.done.set()
        self.log("display_confirmed", **request.result)
        self._active = None
        self._phase = "idle"

    @staticmethod
    def _settings_key(scene, settings):
        return (scene, settings.get("lyrics_display_mode"))

    def _fail(self, message, include_pending=False):
        self._last_error = str(message)
        requests = [self._active]
        if include_pending:
            requests.append(self._pending)
            self._pending = None
        for request in requests:
            if request:
                request.error = self._last_error
                request.done.set()
        self._active = None
        self._phase = "error"
        self.log("display_failed", error=self._last_error)
