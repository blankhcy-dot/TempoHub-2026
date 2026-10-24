"""Acknowledged display transport for the classic Halo PixelBar EC protocol.

This module has no Qt dependency. The host calls tick() on its device/GUI
thread; the HID reader only queues normalized reports through feed_report().
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import deque


WIDTH, HEIGHT = 256, 32
SCREEN_QUERY, SCREEN_SET, IMAGE_SET, TEXT_SET = 0xEE, 0xEF, 0x17, 0xE8
CANVAS_CATEGORY = 7
CANVAS_OPTION = 1
# Transfer ACKs do not prove that firmware is displaying the uploaded bitmap.
# Enable this only after the scene/option mapping passes a physical display test.
IMAGE_DISPLAY_MAPPING_VERIFIED = True
SCENES = ("lyrics", "audio", "notifications", "performance")


def encode_legacy_frame(matrix, category=CANVAS_CATEGORY, duration_ms=100):
    if len(matrix) != HEIGHT or any(len(row) != WIDTH for row in matrix):
        raise ValueError("画面必须为 256×32 点阵")
    if not 0 <= category <= 7 or not 1 <= duration_ms <= 65535:
        raise ValueError("无效的画面参数")
    pixels = bytearray(WIDTH * HEIGHT // 8)
    for y, row in enumerate(matrix):
        for x, value in enumerate(row):
            if value not in (0, 1):
                raise ValueError("画面只能包含 0 或 1")
            if value:
                pixels[(y // 8) * WIDTH + x] |= 1 << (y % 8)
    output = bytearray()
    for page in range(8):
        output.extend((category, page >> 8, page & 255, duration_ms >> 8, duration_ms & 255))
        output.extend(pixels[page * 128:(page + 1) * 128])
    return bytes(output)


def parse_legacy_screen(payload):
    if len(payload) < 12:
        return None
    return {"rgb": list(payload[1:4]), "group": payload[4], "mode": payload[5],
            "option0": payload[6], "option1": payload[7], "option2": payload[8],
            "music_enabled": payload[9], "music_kind": payload[10], "lyric_mode": payload[11]}


class DisplayRequest:
    def __init__(self, scene, settings, force=True):
        if scene not in SCENES:
            raise ValueError("未知显示场景")
        self.scene, self.settings, self.force = scene, dict(settings), bool(force)
        self.done = threading.Event()
        self.result, self.error = None, None


class DeviceDisplay:
    """One in-flight image at a time, bounded retries, verified scene selection."""

    def __init__(self, transport_provider, frame_provider, text_provider, log, clock=time.monotonic):
        self.transport_provider = transport_provider
        self.frame_provider = frame_provider
        self.text_provider = text_provider
        self.log, self.clock = log, clock
        self._lock = threading.RLock()
        self._reports = deque(maxlen=128)
        self._pending = None
        self._active = None
        self._transport = None
        self._transport_key = None
        self._native = None
        self._native_at = 0.0
        self._phase = "idle"
        self._sent_at = 0.0
        self._phase_deadline = 0.0
        self._commands = deque()
        self._setting_command = None
        self._frame = None
        self._frame_hash = None
        self._last_frame_hash = None
        self._offset = 0
        self._packet_size = 50
        self._packet_index = 0
        self._cursor_retries = 0
        self._started_at = 0.0
        self._deadline = 0.0
        self._last_frame_at = 0.0
        self._next_auto_attempt = 0.0
        self._displayed_scene = None
        self._displayed_style = None
        self._displayed_performance_style = None
        self._last_error = None
        self._frame_count = 0
        self._last_latency_ms = None
        self._configuration = None
        self._lyrics_text = None
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
        if index not in (SCREEN_QUERY, SCREEN_SET, IMAGE_SET, TEXT_SET):
            return
        with self._lock:
            self._reports.append((self.clock(), int(index), list(payload or []), source))

    def is_image_request_active(self):
        with self._lock:
            return any(request and request.scene != "lyrics" for request in (self._active, self._pending))

    def snapshot(self):
        with self._lock:
            native = dict(self._native or {})
            return {"connected": self._transport is not None,
                    "protocol": "legacy_ec" if self._transport is not None else None,
                    "phase": self._phase, "pending": self._active is not None or self._pending is not None,
                    "scene": self._displayed_scene, "audio_mode": self._displayed_style,
                    "performance_mode": self._displayed_performance_style,
                    "verified": (self._displayed_scene is not None and self._last_error is None
                                 and self._home_matches(self._displayed_scene)
                                 and (self._displayed_scene == "lyrics" or IMAGE_DISPLAY_MAPPING_VERIFIED)),
                    "transfer_verified": self._displayed_scene is not None and self._last_error is None,
                    "last_error": self._last_error, "last_latency_ms": self._last_latency_ms,
                    "frames_completed": self._frame_count, "packet_index": self._packet_index,
                    "frame_offset": self._offset, "native": native,
                    "lyrics": {"mode_group_index": native.get("group"),
                               "is_lyric_enabled": native.get("music_enabled") == 1 and native.get("music_kind") == 0,
                               "lyrics_display_mode": native.get("lyric_mode")}}

    def tick(self, settings, auto_refresh=True):
        with self._lock:
            now = self.clock()
            try:
                transport = self.transport_provider()
                if transport is None:
                    raise RuntimeError("音响未连接，请检查 USB 数据线")
                if transport.protocol != "legacy_ec":
                    raise RuntimeError("此设备的显示协议尚未验证")
                if transport.key != self._transport_key:
                    self._transport, self._transport_key = transport, transport.key
                    self._native = None
                    self._last_frame_hash = None
                    self._displayed_scene = None
                    self._configuration = None
                    self._last_error = None
                    self._reports.clear()
                    if self._active:
                        self._fail("音响连接已变化，请重新应用显示")
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
                        self._native, self._native_at = native, stamp
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
            scene = str(settings.get("scene", "lyrics"))
            configuration = self._settings_key(scene, settings)
            if request is None and auto_refresh and now >= self._next_auto_attempt:
                if configuration != self._configuration or (self._native and not self._home_matches(scene)):
                    request = DisplayRequest(scene, settings, True)
                elif scene != "lyrics" and now - self._last_frame_at >= 0.4:
                    request = DisplayRequest(scene, settings, False)
            if request is None:
                if now >= self._next_status_query:
                    try:
                        self._transport.send("query", None)
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
        self._deadline = self._started_at + 4.5
        self._cursor_retries = 0
        self._packet_index = self._offset = 0
        self._frame = None
        self._last_error = None
        try:
            if request.scene != "lyrics":
                self._frame = encode_legacy_frame(self.frame_provider(request.scene))
                self._frame_hash = hashlib.sha256(self._frame).hexdigest()
                if (not request.force and self._frame_hash == self._last_frame_hash
                        and self._displayed_scene == request.scene and self._home_matches()):
                    self._complete(frame_transmitted=False)
                    return
            if self._native is None:
                self._send("query", phase="initial_query")
            else:
                self._prepare()
        except Exception as error:
            self._fail(str(error))

    def _prepare(self):
        native = self._native
        rgb = native["rgb"]
        group = native["group"]
        if self._active.scene == "lyrics":
            mode = int(self._active.settings.get("lyrics_display_mode", 1) or 1)
            self._commands = deque([[1, *rgb, group, 0, 1, 0, mode]])
        elif not self._active.force and self._home_matches():
            self._begin_image()
            return
        else:
            self._commands = deque([[2, *rgb, group, 0, 0, 255, 255],
                                    [2, *rgb, group, 1, CANVAS_CATEGORY, 255, 255],
                                    [1, *rgb, group, 1, CANVAS_CATEGORY, CANVAS_OPTION, 255]])
        self._next_setting()

    def _next_setting(self):
        if self._commands:
            self._setting_command = self._commands.popleft()
            self._send("screen", self._setting_command, "setting")
        else:
            self._send("query", phase="verify_home")

    def _home_matches(self, scene=None):
        native = self._native or {}
        scene = scene or self._active.scene
        if scene == "lyrics":
            return native.get("music_enabled") == 1 and native.get("music_kind") == 0
        return (native.get("music_enabled") == 0 and native.get("mode") == 1
                and native.get("option0") == CANVAS_CATEGORY and native.get("option1") == CANVAS_OPTION)

    def _begin_image(self):
        size = len(self._frame)
        self._offset = self._packet_index = 0
        self._send("image", [0, 0, *size.to_bytes(4, "big")], "image_ready")

    def _send_image_chunk(self):
        if self._offset >= len(self._frame):
            self._send("image", [0, 4], "image_finish")
            return
        end = min(len(self._frame), self._offset + self._packet_size)
        chunk = self._frame[self._offset:end]
        self._send("image", [0, 2, self._packet_index >> 8, self._packet_index & 255, *chunk], "image_data")
        self._offset = end
        self._packet_index += 1
        if self._offset == len(self._frame):
            # The official classic uploader queues END immediately after its
            # last data packet. A160 need not send a final NEXT acknowledgement.
            self._send("image", [0, 4], "image_finish")

    def _receive(self, index, payload):
        try:
            if self._phase == "initial_query" and index == SCREEN_QUERY and self._native:
                self._prepare()
            elif self._phase == "setting" and index == SCREEN_SET:
                match_length = 8 if self._setting_command[0] == 1 else 7
                if payload[:match_length] == self._setting_command[:match_length]:
                    self._next_setting()
            elif self._phase == "image_verify_home" and index == SCREEN_QUERY:
                if self._home_matches():
                    self._complete()
                else:
                    self._fail("图像传输完成，但音响未处于所选显示场景")
            elif self._phase == "verify_home" and index == SCREEN_QUERY:
                if not self._home_matches():
                    self._fail("音响未切换到所选显示场景")
                elif self._active.scene == "lyrics":
                    text = str(self.text_provider() or "等待播放音乐")
                    data = text.encode("utf-8")[:55].decode("utf-8", "ignore").encode("utf-8")
                    self._send("text", [14, len(data), *data], "lyric_text")
                else:
                    self._begin_image()
            elif self._phase == "lyric_text" and index == TEXT_SET:
                if payload and payload[0] == 1:
                    self._complete()
                else:
                    self._fail("音响未接受当前歌词")
            elif index == IMAGE_SET and self._phase.startswith("image_"):
                if len(payload) < 2 or payload[0] != 0:
                    return
                state = payload[1]
                if state in (7, 8):
                    self._fail("音响拒绝了当前图像")
                elif state == 1 and self._phase == "image_ready":
                    if len(payload) < 4:
                        self._fail("音响返回的图像传输参数不完整")
                        return
                    size = (payload[2] << 8) | payload[3]
                    if size < 1:
                        self._fail("音响返回无效的图像分包大小")
                        return
                    self._packet_size = min(50, size)
                    self._send_image_chunk()
                elif state == 3 and self._phase == "image_data" and len(payload) >= 4:
                    acknowledged_packet = (payload[2] << 8) | payload[3]
                    if acknowledged_packet == self._packet_index - 1:
                        self._send_image_chunk()
                elif (state == 5 and self._phase in ("image_data", "image_finish")
                      and self._offset == len(self._frame)):
                    # A160 firmware acknowledges the final data packet with
                    # VERIFIED directly, without a separate NEXT/END roundtrip.
                    self._send("query", phase="image_verify_home")
                elif state == 6 and self._phase == "image_data" and len(payload) >= 4:
                    packet = (payload[2] << 8) | payload[3]
                    if self._cursor_retries >= 2 or packet * self._packet_size >= len(self._frame):
                        self._fail("音响图像分包校验失败")
                        return
                    self._cursor_retries += 1
                    self._packet_index = packet
                    self._offset = packet * self._packet_size
                    self._send_image_chunk()
        except Exception as error:
            self._fail(str(error))

    def _complete(self, frame_transmitted=True):
        request = self._active
        self._displayed_scene = request.scene
        self._displayed_style = request.settings.get("audio_mode", "bars")
        self._displayed_performance_style = request.settings.get("performance_mode", "tiles")
        self._configuration = self._settings_key(request.scene, request.settings)
        self._last_error = None
        self._last_frame_at = self.clock()
        self._last_latency_ms = round((self._last_frame_at - self._started_at) * 1000, 2)
        if self._frame:
            self._last_frame_hash = self._frame_hash
            if frame_transmitted:
                self._frame_count += 1
        request.result = {"scene": request.scene,
                          "performance_mode": self._displayed_performance_style,
                          "verified": request.scene == "lyrics" or IMAGE_DISPLAY_MAPPING_VERIFIED,
                          "transfer_verified": True, "protocol": "legacy_ec",
                          "latency_ms": self._last_latency_ms, "frame_bytes": len(self._frame or b"")}
        request.done.set()
        self.log("display_confirmed", **request.result)
        self._active = None
        self._phase = "idle"

    @staticmethod
    def _settings_key(scene, settings):
        keys = ("audio_mode", "audio_sensitivity") if scene == "audio" else (
            ("performance_mode", "perf_show_fps", "perf_show_cpu", "perf_show_gpu", "perf_show_memory")
            if scene == "performance" else ("lyrics_display_mode",))
        return (scene, *(settings.get(key) for key in keys))

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
        self._next_auto_attempt = self.clock() + 2.0
        self.log("display_failed", error=self._last_error)
