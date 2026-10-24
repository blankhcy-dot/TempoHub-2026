"""Runtime scenes for the Halo PixelBar 256x32 canvas."""

from __future__ import annotations

import asyncio
import csv
import ctypes
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen, QPolygonF


SCREEN_WIDTH = 256
SCREEN_HEIGHT = 32
AUDIO_BARS = 32
AUDIO_MODES = ("bars", "wave", "vu", "mirror", "waterfall", "pulse", "particles", "orbit", "mountains")
PERFORMANCE_MODES = ("tiles", "gauges", "trends", "hud", "focus", "minimal")
HISTORY_LENGTH = 60

# Authored bitmap glyphs, with explicit empty counters and one-pixel strokes.
# Keep digits five columns wide so changing values do not shift their spacing.
_PIXEL_GLYPHS = {
    " ": "00/00/00/00/00/00/00",
    "A": "01110/10001/10001/11111/10001/10001/10001",
    "B": "11110/10001/10001/11110/10001/10001/11110",
    "C": "01111/10000/10000/10000/10000/10000/01111",
    "D": "11110/10001/10001/10001/10001/10001/11110",
    "E": "11111/10000/10000/11110/10000/10000/11111",
    "F": "11111/10000/10000/11110/10000/10000/10000",
    "G": "01111/10000/10000/10111/10001/10001/01111",
    "H": "10001/10001/10001/11111/10001/10001/10001",
    "I": "111/010/010/010/010/010/111",
    "J": "00111/00010/00010/00010/00010/10010/01100",
    "K": "10001/10010/10100/11000/10100/10010/10001",
    "L": "10000/10000/10000/10000/10000/10000/11111",
    "M": "10001/11011/10101/10101/10001/10001/10001",
    "N": "10001/11001/10101/10011/10001/10001/10001",
    "O": "01110/10001/10001/10001/10001/10001/01110",
    "P": "11110/10001/10001/11110/10000/10000/10000",
    "Q": "01110/10001/10001/10001/10101/10010/01101",
    "R": "11110/10001/10001/11110/10100/10010/10001",
    "S": "01111/10000/10000/01110/00001/00001/11110",
    "T": "11111/00100/00100/00100/00100/00100/00100",
    "U": "10001/10001/10001/10001/10001/10001/01110",
    "V": "10001/10001/10001/10001/10001/01010/00100",
    "W": "10001/10001/10001/10101/10101/11011/10001",
    "X": "10001/10001/01010/00100/01010/10001/10001",
    "Y": "10001/10001/01010/00100/00100/00100/00100",
    "Z": "11111/00001/00010/00100/01000/10000/11111",
    "a": "00000/00000/01110/00001/01111/10001/01111",
    "b": "10000/10000/10110/11001/10001/10001/11110",
    "c": "00000/00000/01111/10000/10000/10000/01111",
    "d": "00001/00001/01101/10011/10001/10001/01111",
    "e": "00000/00000/01110/10001/11111/10000/01111",
    "f": "00110/01001/01000/11100/01000/01000/01000",
    "g": "00000/01111/10001/10001/01111/00001/01110",
    "h": "10000/10000/10110/11001/10001/10001/10001",
    "i": "010/000/110/010/010/010/111",
    "j": "001/000/011/001/001/101/010",
    "k": "10000/10000/10010/10100/11000/10100/10010",
    "l": "110/010/010/010/010/010/111",
    "m": "00000/00000/11010/10101/10101/10101/10101",
    "n": "00000/00000/10110/11001/10001/10001/10001",
    "o": "00000/00000/01110/10001/10001/10001/01110",
    "p": "00000/11110/10001/10001/11110/10000/10000",
    "q": "00000/01111/10001/10001/01111/00001/00001",
    "r": "00000/00000/10110/11001/10000/10000/10000",
    "s": "00000/00000/01111/10000/01110/00001/11110",
    "t": "01000/01000/11100/01000/01000/01001/00110",
    "u": "00000/00000/10001/10001/10001/10011/01101",
    "v": "00000/00000/10001/10001/10001/01010/00100",
    "w": "00000/00000/10001/10001/10101/10101/01010",
    "x": "00000/00000/10001/01010/00100/01010/10001",
    "y": "00000/10001/10001/10001/01111/00001/01110",
    "z": "00000/00000/11111/00010/00100/01000/11111",
    "0": "01110/10001/10001/10001/10001/10001/01110",
    "1": "00100/01100/00100/00100/00100/00100/01110",
    "2": "01110/10001/00001/00010/00100/01000/11111",
    "3": "11110/00001/00001/01110/00001/00001/11110",
    "4": "00010/00110/01010/10010/11111/00010/00010",
    "5": "11111/10000/10000/11110/00001/00001/11110",
    "6": "01110/10000/10000/11110/10001/10001/01110",
    "7": "11111/00001/00010/00100/01000/01000/01000",
    "8": "01110/10001/10001/01110/10001/10001/01110",
    "9": "01110/10001/10001/01111/00001/00001/01110",
    "%": "0100001/1010010/0100100/0001000/0010010/0100101/1000010",
    ".": "0/0/0/0/0/0/1",
    ",": "00/00/00/00/00/01/10",
    ":": "0/0/1/0/0/1/0",
    ";": "00/00/01/00/00/01/10",
    "-": "000/000/000/111/000/000/000",
    "_": "00000/00000/00000/00000/00000/00000/11111",
    "+": "00000/00100/00100/11111/00100/00100/00000",
    "=": "00000/00000/11111/00000/11111/00000/00000",
    "/": "00001/00010/00010/00100/01000/01000/10000",
    "\\": "10000/01000/01000/00100/00010/00010/00001",
    "(": "001/010/100/100/100/010/001",
    ")": "100/010/001/001/001/010/100",
    "[": "111/100/100/100/100/100/111",
    "]": "111/001/001/001/001/001/111",
    "<": "0001/0010/0100/1000/0100/0010/0001",
    ">": "1000/0100/0010/0001/0010/0100/1000",
    "!": "1/1/1/1/1/0/1",
    "?": "01110/10001/00001/00010/00100/00000/00100",
    "'": "1/1/0/0/0/0/0",
    '"': "101/101/000/000/000/000/000",
    "#": "01010/01010/11111/01010/11111/01010/01010",
    "*": "00000/10101/01110/11111/01110/10101/00000",
    "@": "01110/10001/10111/10101/10111/10000/01110",
    "&": "01100/10010/10100/01000/10101/10010/01101",
    "|": "1/1/1/1/1/1/1",
    "~": "00000/00000/01001/10110/00000/00000/00000",
    "°": "010/101/010/000/000/000/000",
}
_PIXEL_GLYPHS = {character: tuple(rows.split("/")) for character, rows in _PIXEL_GLYPHS.items()}


@lru_cache(maxsize=256)
def _pixel_glyph_segments(character, scale):
    rows = _PIXEL_GLYPHS[character]
    segments = []
    for y, row in enumerate(rows):
        if scale == 1:
            x = 0
            while x < len(row):
                if row[x] == "0":
                    x += 1
                    continue
                end = x
                while end + 1 < len(row) and row[end + 1] == "1":
                    end += 1
                segments.append((x, y, end, y))
                x = end + 1
            continue
        for x, bit in enumerate(row):
            if bit != "1":
                continue
            segments.append((x * scale, y * scale, x * scale, y * scale))
            for dx, dy in ((1, 0), (0, 1), (-1, 1), (1, 1)):
                nx, ny = x + dx, y + dy
                if not (0 <= ny < 7 and 0 <= nx < len(row)) or rows[ny][nx] != "1":
                    continue
                # Diagonals connect only isolated corners, keeping the insides
                # of E, B, P and other right-angle glyphs open when enlarged.
                if dx and dy and (rows[y][nx] == "1" or rows[ny][x] == "1"):
                    continue
                segments.append((x * scale, y * scale, nx * scale, ny * scale))
    return tuple(segments)


def _clamp(value, low, high):
    return max(low, min(high, value))


def _safe_number(value, digits=0):
    if value is None:
        return "--"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    return f"{number:.{digits}f}" if digits else str(int(round(number)))


class SceneEngine:
    """Collect desktop telemetry and render monochrome device frames."""

    def __init__(self, app_dir, log):
        self.app_dir = Path(app_dir)
        self.log = log
        self._lock = threading.RLock()
        self._configure_lock = threading.RLock()
        self._fps_start_lock = threading.Lock()
        self._render_lock = threading.Lock()
        self._render_cache = None
        self._fft_plan = None
        self._audio_visual = None
        self._gpu_retry_at = 0.0
        self._settings = {}
        self._stop_event = threading.Event()
        self._audio_stream = None
        self._audio_capture_thread = None
        self._audio_capture_stop = threading.Event()
        self._audio_error = None
        self._audio_levels = [0.0] * AUDIO_BARS
        self._audio_wave = [0.0] * 128
        self._audio_rms_db = -80.0
        self._audio_peak_db = -80.0
        self._history = {
            "fps": deque(maxlen=HISTORY_LENGTH),
            "cpu": deque(maxlen=HISTORY_LENGTH),
            "gpu": deque(maxlen=HISTORY_LENGTH),
            "memory": deque(maxlen=HISTORY_LENGTH),
        }
        self._metrics = {
            "fps": None,
            "cpu": None,
            "gpu": None,
            "gpu_temp": None,
            "cpu_temp": None,
            "memory": None,
            "foreground": "",
        }
        self._metric_error = None
        self._cpu_temp_checked = False
        self._alert = None
        self._notification_revision = 0
        self._notification_status = "正在连接 Windows 通知"
        self._notification_error = None
        self._seen_notifications = set()
        self._window_baseline = {}
        self._last_window_alert = 0.0
        self._fps_status = "未启用"
        self._fps_error = None
        self._fps_csv_path = Path(tempfile.gettempdir()) / "TempoHubPresentMon.csv"
        self._fps_offset = 0
        self._fps_rows = {}
        self._fps_thread = None
        self._thread = threading.Thread(
            target=self._system_loop,
            daemon=True,
            name="tempo-scene-system",
        )
        self._thread.start()
        self._notification_thread = threading.Thread(
            target=self._notification_loop,
            daemon=True,
            name="tempo-scene-notifications",
        )
        self._notification_thread.start()

    def configure(self, settings):
        # Device enumeration and stream start/stop must not overlap between
        # concurrent settings requests.
        with self._configure_lock:
            with self._lock:
                previous_scene = self._settings.get("scene", "lyrics")
                self._settings = dict(settings)
                scene = self._settings.get("scene", "lyrics")
                if (self._alert and not self._alert.get("test")
                        and not self._notification_allowed(self._alert.get("app", ""))):
                    self._alert = None
                    self._notification_revision = getattr(self, "_notification_revision", 0) + 1
            with self._render_lock:
                self._render_cache = None
            if scene == "audio":
                self._ensure_audio_stream()
            elif previous_scene == "audio":
                self._stop_audio_stream()
            if scene != "performance":
                self._fps_status = (
                    "后台采集" if self._fps_thread and self._fps_thread.is_alive() else self._fps_status
                )

    def snapshot(self):
        with self._lock:
            now = time.monotonic()
            alert = dict(self._alert or {})
            if alert and now >= float(alert.get("until", 0.0)):
                alert = {}
            return {
                "audio": {
                    "levels": list(self._audio_levels),
                    "wave": list(self._audio_wave),
                    "rms_db": self._audio_rms_db,
                    "peak_db": self._audio_peak_db,
                    "error": self._audio_error,
                },
                "performance": {
                    **self._metrics,
                    "history": {
                        key: list(values)
                        for key, values in self._history.items()
                    },
                    "error": self._metric_error,
                    "fps_status": self._fps_status,
                    "fps_error": self._fps_error,
                },
                "notifications": {
                    "status": self._notification_status,
                    "error": self._notification_error,
                    "latest": alert,
                },
            }

    def trigger_notification(self, app_name, text):
        # A local test is an explicit action, independent of passive monitoring.
        self._set_alert(app_name, text, force=True)

    def notification_display_state(self):
        with self._lock:
            if self._alert and time.monotonic() >= float(self._alert.get("until", 0.0)):
                self._alert = None
                self._notification_revision = getattr(self, "_notification_revision", 0) + 1
            return {"revision": getattr(self, "_notification_revision", 0), "active": bool(self._alert)}

    def start_fps_capture(self):
        with self._fps_start_lock:
            return self._start_fps_capture()

    def _start_fps_capture(self):
        if self._fps_thread is not None and self._fps_thread.is_alive():
            return {"status": self._fps_status, "already_running": True}
        executable = next(
            (
                path
                for path in (
                    self.app_dir / "tools" / "PresentMon-2.6.0-x64.exe",
                    self.app_dir / "tools" / "PresentMon.exe",
                )
                if path.is_file()
            ),
            None,
        )
        if executable is None:
            self._fps_status = "缺少 PresentMon"
            self._fps_error = "安装目录中未找到 PresentMon"
            return {"status": self._fps_status, "error": self._fps_error}
        try:
            self._fps_csv_path.unlink(missing_ok=True)
        except OSError:
            pass
        self._fps_offset = 0
        with self._lock:
            self._fps_rows.clear()
        arguments = (
            f'--output_file "{self._fps_csv_path}" --v1_metrics '
            "--no_console_stats --stop_existing_session "
            "--session_name TempoHubPixelBar --timed 3600 "
            "--terminate_after_timed"
        )
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            str(executable),
            arguments,
            str(executable.parent),
            0,
        )
        if result <= 32:
            self._fps_status = "启动失败"
            self._fps_error = f"ShellExecuteW={result}"
            return {"status": self._fps_status, "error": self._fps_error}
        self._fps_status = "等待管理员授权"
        self._fps_error = None
        self._fps_thread = threading.Thread(
            target=self._fps_reader_loop,
            daemon=True,
            name="tempo-scene-presentmon",
        )
        self._fps_thread.start()
        return {"status": self._fps_status}

    def render_matrix(self, scene=None):
        # The device and settings preview can request the same frame at once.
        with self._render_lock:
            scene = scene or self._settings.get("scene", "lyrics")
            with self._lock:
                cache_key = (scene, getattr(self, "_notification_revision", 0) if scene == "notifications" else None)
            now = time.monotonic()
            cached = self._render_cache
            if cached is not None and cached[0] == cache_key and now - cached[1] < 0.08:
                return cached[2]
            matrix = self._render_matrix(scene)
            self._render_cache = (cache_key, now, matrix)
            return matrix

    def _render_matrix(self, scene):
        with self._lock:
            settings = dict(self._settings)
            signal = self.snapshot()
        scene = scene or settings.get("scene", "lyrics")
        if scene == "lyrics":
            return None
        image = QImage(
            SCREEN_WIDTH,
            SCREEN_HEIGHT,
            QImage.Format.Format_Grayscale8,
        )
        image.fill(QColor("black"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, False)
        painter.setPen(QColor("white"))
        if scene == "audio":
            self._draw_audio(painter, settings, signal["audio"])
        elif scene == "notifications":
            self._draw_notifications(painter, settings, signal["notifications"])
        elif scene == "performance":
            self._draw_performance(painter, settings, signal["performance"])
        painter.end()
        return self._image_to_matrix(image)

    @staticmethod
    def _image_to_matrix(image):
        if image.format() != QImage.Format.Format_Grayscale8:
            image = image.convertToFormat(QImage.Format.Format_Grayscale8)
        pixels = image.constBits().asstring(image.sizeInBytes())
        stride = image.bytesPerLine()
        threshold = bytes(0 if value < 96 else 1 for value in range(256))
        binary = pixels.translate(threshold)
        return [list(binary[y * stride:y * stride + SCREEN_WIDTH])
                for y in range(SCREEN_HEIGHT)]

    def _font(self, size, family="Consolas", bold=False):
        font = QFont(family)
        font.setPixelSize(int(size))
        font.setBold(bool(bold))
        font.setKerning(False)
        return font

    def _draw_text(self, painter, x, y, text, size=8, family="Consolas", bold=False,
                   align="left", max_width=None):
        text = str(text).replace("\r", " ").replace("\n", " ").replace("\t", " ")
        scale = max(1, int(size) // 7)
        spacing = scale
        fallback = any(character not in _PIXEL_GLYPHS for character in text)
        font = self._font(size, "Microsoft YaHei UI" if family == "Consolas" else family, False) if fallback else None
        metrics = QFontMetricsF(font) if fallback else None
        advances = []
        for character in text:
            rows = _PIXEL_GLYPHS.get(character)
            width = (len(rows[0]) - 1) * scale + 1 if rows is not None else math.ceil(metrics.horizontalAdvance(character))
            advances.append(max(1, width))
        width = sum(advances) + max(0, len(text) - 1) * spacing
        cursor = int(round(x - width / 2 if align == "center" else x))
        baseline = int(round(y))
        top = baseline - (6 * scale + 1)
        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, False)
            painter.setPen(QPen(QColor("white"), 1))
            if max_width is not None:
                left = x - max_width / 2 if align == "center" else x
                painter.setClipRect(QRectF(left, 0, max_width, SCREEN_HEIGHT), Qt.ClipOperation.IntersectClip)
            if font is not None:
                painter.setFont(font)
            for character, advance in zip(text, advances):
                if character in _PIXEL_GLYPHS:
                    for x1, y1, x2, y2 in _pixel_glyph_segments(character, scale):
                        if x1 == x2 and y1 == y2:
                            painter.drawPoint(cursor + x1, top + y1)
                        else:
                            painter.drawLine(cursor + x1, top + y1, cursor + x2, top + y2)
                else:
                    painter.drawText(QPointF(cursor, baseline), character)
                cursor += advance + spacing
        finally:
            painter.restore()
        return width

    def _draw_audio(self, painter, settings, audio):
        mode = str(settings.get("audio_mode", "bars"))
        sensitivity = _clamp(
            float(settings.get("audio_sensitivity", 55) or 55) / 55.0,
            0.35,
            3.0,
        )
        levels = [
            _clamp(float(level) * sensitivity, 0.0, 1.0)
            for level in (audio.get("levels") or [0.0] * AUDIO_BARS)
        ]
        wave = audio.get("wave") or [0.0] * 128
        error = audio.get("error")
        visual = self._audio_animation(mode, levels)
        smooth = visual["levels"]
        peaks = visual["peaks"]
        energy = math.sqrt(sum(smooth) / max(1, len(smooth)))
        phase = visual["phase"]
        if mode == "wave":
            points = [
                QPointF(
                    index * (SCREEN_WIDTH - 1) / max(1, len(wave) - 1),
                    SCREEN_HEIGHT / 2 - _clamp(float(value) * sensitivity, -1.0, 1.0) * (SCREEN_HEIGHT - 5) / 2,
                )
                for index, value in enumerate(wave)
            ]
            painter.setPen(QPen(QColor("white"), 1))
            painter.drawPolyline(QPolygonF(points))
        elif mode == "vu":
            self._draw_text(painter, 4, 8, "SYSTEM AUDIO", 7, bold=True)
            self._draw_text(painter, 1, 18, "PK", 7, bold=True)
            self._draw_text(painter, 1, 29, "RM", 7, bold=True)
            peak_db = audio.get("peak_db")
            rms_db = audio.get("rms_db")
            peak = _clamp((float(peak_db if peak_db is not None else -80.0) + 60.0) / 60.0, 0.0, 1.0)
            rms = _clamp((float(rms_db if rms_db is not None else -80.0) + 60.0) / 60.0, 0.0, 1.0)
            painter.drawRect(QRectF(15, 12, 205, 5))
            painter.fillRect(QRectF(15, 12, 205 * peak, 5), QColor("white"))
            painter.drawRect(QRectF(15, 22, 205, 5))
            painter.fillRect(QRectF(15, 22, 205 * rms, 5), QColor("white"))
            self._draw_text(
                painter,
                225,
                17,
                f"{peak_db if peak_db is not None else -80:.0f}dB",
                7,
            )
        elif mode == "mirror":
            for index in range(16):
                level = sum(smooth[index * 2:index * 2 + 2]) / 2
                peak = max(peaks[index * 2:index * 2 + 2])
                half = max(1, round(level * 14))
                cap = max(half, round(peak * 14))
                for x in (129 - (index + 1) * 8, 130 + index * 8):
                    painter.fillRect(QRectF(x, 16 - half, 5, half * 2), QColor("white"))
                    painter.drawLine(QPointF(x, 16 - cap), QPointF(x + 4, 16 - cap))
                    painter.drawLine(QPointF(x, 15 + cap), QPointF(x + 4, 15 + cap))
        elif mode == "waterfall":
            for y, row in enumerate(visual["history"]):
                for index, value in enumerate(row):
                    x = index * 8
                    value *= 1.0 - y / (SCREEN_HEIGHT - 1) * 0.65
                    if value > 0.65:
                        painter.fillRect(QRectF(x + 1, y, 6, 1), QColor("white"))
                    elif value > 0.35:
                        painter.drawLine(QPointF(x + 2, y), QPointF(x + 5, y))
                    elif value > 0.12:
                        painter.drawPoint(QPointF(x + 2 + (y % 2) * 2, y))
        elif mode == "pulse":
            for layer in (1.0, -1.0, 0.48):
                points = []
                for index in range(128):
                    x = index * 255 / 127
                    envelope = 0.25 + 0.75 * math.sin(math.pi * index / 127)
                    carrier = (math.sin(x / 19 - phase * 5) * 0.65
                               + math.sin(x / 7 + phase * 3) * 0.35)
                    y = 15.5 + carrier * envelope * energy * 15.5 * layer
                    points.append(QPointF(x, y))
                painter.drawPolyline(QPolygonF(points))
        elif mode == "particles":
            for index in range(80):
                band = (index * 11) % AUDIO_BARS
                strength = smooth[band]
                if strength < 0.08 or strength < ((index * 37) % 83) / 110:
                    continue
                x = ((index * 53.3 + phase * (12 + band * 0.9)) % 256)
                y = 15.5 + math.sin(index * 2.39 + phase * 0.7) * (6 + strength * 9)
                tail = round(strength * 5) if index % 4 == 0 else 0
                painter.drawLine(QPointF(max(0, x - tail), y), QPointF(x, y))
                if strength > 0.75 and index % 7 == 0:
                    painter.drawPoint(QPointF(x, _clamp(y + 1, 0, 31)))
        elif mode == "orbit":
            for ring in (0, 1):
                rx = 38 + energy * 64 - ring * 20
                ry = 3 + energy * 10 - ring * 1.5
                points = []
                for index in range(65):
                    angle = index * math.tau / 64
                    ripple = math.sin(angle * 5 + phase * 2) * energy * 2
                    points.append(QPointF(128 + math.cos(angle) * (rx + ripple),
                                          15.5 + math.sin(angle) * (ry + ripple * 0.25)))
                painter.drawPolyline(QPolygonF(points))
                for index in range(3):
                    angle = phase * (0.8 + ring * 0.3) + index * math.tau / 3
                    x, y = 128 + math.cos(angle) * rx, 15.5 + math.sin(angle) * ry
                    painter.fillRect(QRectF(x - 1, y - 1, 3, 3), QColor("white"))
            core = 1 + round(energy * 3)
            painter.fillRect(QRectF(128 - core, 15.5 - core, core * 2, core * 2), QColor("white"))
            painter.drawLine(QPointF(4, 15.5), QPointF(24, 15.5))
            painter.drawLine(QPointF(232, 15.5), QPointF(252, 15.5))
            for x in (28, 224):
                height = max(1, round(energy * 8))
                painter.drawLine(QPointF(x, 16 - height), QPointF(x, 15 + height))
        elif mode == "mountains":
            for layer in (2, 1, 0):
                pen = QPen(QColor("white"), 1)
                if layer:
                    pen.setStyle(Qt.PenStyle.DotLine)
                painter.setPen(pen)
                points = []
                shift = int(phase * 2) + layer * 4
                for index in range(AUDIO_BARS):
                    value = smooth[(index + shift) % AUDIO_BARS]
                    y = 30 - layer * 4 - value * (26 - layer * 5)
                    y += math.sin(index * 0.45 + phase * 2 + layer) * energy * 1.7
                    points.append(QPointF(index * 255 / (AUDIO_BARS - 1), _clamp(y, 0, 31)))
                painter.drawPolyline(QPolygonF(points))
            painter.setPen(QPen(QColor("white"), 1))
        else:
            for index in range(AUDIO_BARS):
                level = smooth[index]
                height = max(1, int(round(level * (SCREEN_HEIGHT - 3))))
                painter.fillRect(
                    QRectF(index * 8, SCREEN_HEIGHT - height, 6, height),
                    QColor("white"),
                )
        if error:
            painter.fillRect(QRectF(0, 0, SCREEN_WIDTH, 9), QColor("black"))
            self._draw_text(painter, 3, 8, "AUDIO OFF", 7, bold=True)

    def _audio_animation(self, mode, levels):
        """One bounded, time-based state shared by device and preview rendering."""
        now = time.monotonic()
        levels = list(levels[:AUDIO_BARS])
        levels.extend([0.0] * (AUDIO_BARS - len(levels)))
        visual = getattr(self, "_audio_visual", None)
        if visual is None or visual["mode"] != mode:
            visual = {"mode": mode, "updated": now, "history_at": now,
                      "levels": levels, "peaks": list(levels), "phase": 0.0,
                      "history": deque([list(levels)], maxlen=SCREEN_HEIGHT)}
            self._audio_visual = visual
            return visual
        elapsed = _clamp(now - visual["updated"], 0.0, 1.0)
        visual["updated"] = now
        smooth = []
        for previous, target in zip(visual["levels"], levels):
            rate = 28.0 if target > previous else 6.0
            smooth.append(previous + (target - previous) * (1.0 - math.exp(-elapsed * rate)))
        visual["levels"] = smooth
        visual["peaks"] = [max(level, peak - elapsed * 0.55)
                           for level, peak in zip(smooth, visual["peaks"])]
        energy = sum(smooth) / AUDIO_BARS
        if energy > 0.01:
            visual["phase"] += elapsed * (0.6 + energy * 2.5)
        if now - visual["history_at"] >= 0.08:
            visual["history"].appendleft(list(smooth))
            visual["history_at"] = now
        return visual

    def _draw_notifications(self, painter, settings, state):
        latest = state.get("latest") or {}
        if latest:
            app_name = str(latest.get("app") or "NOTICE")
            app_name = {"微信": "WECHAT", "QQ邮箱": "QQ MAIL"}.get(app_name, app_name.upper())
            text = str(latest.get("text") or "")
            self._draw_text(painter, 4, 10, app_name, 7, bold=True)
            self._draw_text(painter, 4, 28, text, 14, max_width=SCREEN_WIDTH - 8)
            return
        self._draw_text(painter, 4, 9, "MESSAGE MONITOR", 8, bold=True)
        enabled = []
        if settings.get("notify_wechat", True):
            enabled.append("WECHAT")
        if settings.get("notify_qq", True):
            enabled.append("QQ")
        if settings.get("notify_qqmail", True):
            enabled.append("MAIL")
        status = " / ".join(enabled) if enabled else "ALL OFF"
        self._draw_text(painter, 4, 23, status, 9, bold=True)
        painter.drawLine(3, 28, SCREEN_WIDTH - 4, 28)

    def _draw_performance(self, painter, settings, state):
        mode = settings.get("performance_mode", "tiles")
        entries = [(key, label) for key, label in (("fps", "FPS"), ("cpu", "CPU"),
                    ("gpu", "GPU"), ("memory", "MEM")) if settings.get("perf_show_" + key, True)]
        if not entries:
            self._draw_text(painter, 68, 20, "NO METRICS SELECTED", 10, bold=True)
            return
        histories = state.get("history") or {}
        temperature_row = any(key in ("cpu", "gpu") and state.get(key + "_temp") is not None
                              for key, _ in entries)

        def number(key):
            return _safe_number(state.get(key))

        def ratio(key):
            value = state.get(key)
            if value is None:
                return 0.0
            return _clamp(float(value) / (240.0 if key == "fps" else 100.0), 0.0, 1.0)

        def graph(key, rect):
            points = histories.get(key) or []
            numeric = [float(p) for p in points if p is not None]
            maximum = max(60.0, max(numeric, default=0.0) * 1.1) if key == "fps" else 100.0
            # Gaps in unavailable telemetry must remain gaps, not false zeros.
            segment = []
            for index, value in enumerate(points):
                if value is None:
                    if len(segment) > 1:
                        painter.drawPolyline(QPolygonF(segment))
                    segment = []
                    continue
                segment.append(QPointF(rect.left() + index * rect.width() / max(1, len(points) - 1),
                                       rect.bottom() - _clamp(float(value) / maximum, 0.0, 1.0) * rect.height()))
            if len(segment) > 1:
                painter.drawPolyline(QPolygonF(segment))

        painter.setPen(QPen(QColor("white"), 1))
        if mode == "focus":
            key, label = entries[0]
            self._draw_text(painter, 3, 9, label, 8, bold=True)
            self._draw_text(painter, 3, 31, number(key) + ("%" if key != "fps" else ""), 24, bold=True)
            if len(entries) > 1:
                painter.drawLine(110, 1, 110, 30)
                for index, (key, label) in enumerate(entries[1:]):
                    y = index * 10
                    self._draw_text(painter, 116, y + 8, label, 8, bold=True)
                    self._draw_text(painter, 151, y + 8, number(key) + "%", 8)
                    painter.drawRect(188, y + 2, 64, 5)
                    painter.fillRect(190, y + 4, int(60 * ratio(key)), 2, QColor("white"))
            else:
                graph(key, QRectF(116, 4, 136, 23))
            return
        if mode == "trends":
            row_height = 32.0 / len(entries)
            for index, (key, label) in enumerate(entries):
                top = int(index * row_height)
                self._draw_text(painter, 1, top + 7, label, 7, bold=True)
                self._draw_text(painter, 222, top + 7, number(key), 7)
                graph(key, QRectF(29, top + 1, 187, max(3, row_height - 3)))
                if index:
                    for x in range(30, 216, 4):
                        painter.drawPoint(x, top)
            return
        for index, (key, label) in enumerate(entries):
            left = index * SCREEN_WIDTH // len(entries)
            right = (index + 1) * SCREEN_WIDTH // len(entries)
            width = right - left
            text = number(key) + ("%" if key != "fps" else "")
            if mode == "gauges":
                center = left + width // 2
                painter.drawArc(QRectF(center - 17, 1, 34, 34), 30 * 16, 120 * 16)
                painter.drawArc(QRectF(center - 14, 4, 28, 28), 30 * 16, int(120 * 16 * ratio(key)))
                painter.save()
                painter.setClipRect(left, 0, width, 32)
                self._draw_text(painter, center, 23, text, 14, align="center", max_width=width - 8)
                self._draw_text(painter, center, 31, label, 7, align="center", max_width=width - 8)
                painter.restore()
            elif mode == "minimal":
                if index:
                    painter.drawLine(left, 7, left, 25)
                self._draw_text(painter, left + 4, 8, label, 7)
                self._draw_text(painter, left + 4, 25, text, 15, bold=True)
                painter.fillRect(left + 4, 29, int((width - 8) * ratio(key)), 2, QColor("white"))
            elif mode == "hud":
                painter.drawPolyline(QPolygonF([QPointF(left + 1, 7), QPointF(left + 7, 1),
                    QPointF(right - 3, 1), QPointF(right - 3, 25), QPointF(right - 9, 31), QPointF(left + 1, 31)]))
                self._draw_text(painter, left + 8, 9, label, 7, bold=True)
                self._draw_text(painter, left + 8, 23, text, 14, max_width=width - 16)
                for step in range(int(ratio(key) * max(1, (width - 16) // 5))):
                    painter.fillRect(left + 8 + step * 5, 26, 3, 2, QColor("white"))
            else:
                if index:
                    painter.drawLine(left, 1, left, 31)
                heading = label + " " + text
                temperature = state.get(key + "_temp") if key in ("cpu", "gpu") else None
                self._draw_text(painter, left + 3, 8, heading, 7, max_width=width - 6)
                if temperature_row and temperature is not None:
                    self._draw_text(painter, left + 3, 17, _safe_number(temperature) + "°C", 7, max_width=width - 6)
                chart_top = 19 if temperature_row else 11
                rect = QRectF(left + 2, chart_top, width - 5, 30 - chart_top)
                painter.drawRect(rect)
                graph(key, rect.adjusted(1, 1, -1, -1))
        return


    def _notification_allowed(self, app_name):
        category = self._notification_category(str(app_name))
        key = {"微信": "notify_wechat", "QQ": "notify_qq", "QQ邮箱": "notify_qqmail"}.get(category)
        return key is None or bool(self._settings.get(key, True))

    def _set_alert(self, app_name, text, force=False):
        with self._lock:
            if not force and not self._notification_allowed(app_name):
                return False
            self._alert = {
                "app": str(app_name),
                "text": str(text).strip()[:96],
                "time": time.time(),
                "until": time.monotonic() + 5.0,
                "test": bool(force),
            }
            self._notification_revision = getattr(self, "_notification_revision", 0) + 1
            return True

    def _system_loop(self):
        try:
            import psutil
        except Exception as error:
            self._metric_error = f"psutil: {error}"
            psutil = None
        last_gpu = 0.0
        while not self._stop_event.is_set():
            cpu = memory = None
            if psutil is not None:
                try:
                    cpu = float(psutil.cpu_percent(interval=None))
                    memory = float(psutil.virtual_memory().percent)
                except Exception as error:
                    self._metric_error = str(error)
            gpu = self._metrics.get("gpu")
            gpu_temp = self._metrics.get("gpu_temp")
            if time.monotonic() - last_gpu >= 1.0:
                gpu, gpu_temp = self._query_nvidia()
                last_gpu = time.monotonic()
            cpu_temp = self._metrics.get("cpu_temp")
            if not self._cpu_temp_checked:
                cpu_temp = self._query_cpu_temp()
                self._cpu_temp_checked = True
            foreground = self._foreground_process_name(psutil)
            with self._lock:
                self._metrics.update(
                    {
                        "cpu": cpu,
                        "gpu": gpu,
                        "gpu_temp": gpu_temp,
                        "cpu_temp": cpu_temp,
                        "memory": memory,
                        "foreground": foreground,
                    }
                )
                for key, value in (
                    ("cpu", cpu),
                    ("gpu", gpu),
                    ("memory", memory),
                ):
                    self._history[key].append(value)
            self._update_fps_from_rows()
            self._stop_event.wait(1.0)

    def _query_nvidia(self):
        if time.monotonic() < self._gpu_retry_at:
            return None, None
        executable = "nvidia-smi.exe"
        try:
            result = subprocess.run(
                [
                    executable,
                    "--query-gpu=utilization.gpu,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0 or not result.stdout.strip():
                self._gpu_retry_at = time.monotonic() + 30.0
                return None, None
            usage, temperature = result.stdout.splitlines()[0].split(",")[:2]
            return float(usage.strip()), float(temperature.strip())
        except Exception:
            self._gpu_retry_at = time.monotonic() + 30.0
            return None, None

    def _query_cpu_temp(self):
        script = (
            "Get-CimInstance -Namespace root/WMI "
            "-ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop | "
            "Select-Object -First 1 -ExpandProperty CurrentTemperature"
        )
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    script,
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0:
                return None
            return round(float(result.stdout.strip()) / 10.0 - 273.15, 1)
        except Exception:
            return None

    def _foreground_process_name(self, psutil_module):
        try:
            user32 = ctypes.windll.user32
            handle = user32.GetForegroundWindow()
            process_id = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id))
            if psutil_module is not None:
                return psutil_module.Process(process_id.value).name()
        except Exception:
            pass
        return ""

    def _ensure_audio_stream(self):
        with self._lock:
            if (
                self._audio_stream is not None
                or (
                    self._audio_capture_thread is not None
                    and self._audio_capture_thread.is_alive()
                )
            ):
                return
        try:
            import numpy as np
            vendor_dir = str(self.app_dir / "vendor")
            if vendor_dir not in sys.path:
                sys.path.insert(0, vendor_dir)
            try:
                import soundcard as sc

                loopbacks = [
                    device
                    for device in sc.all_microphones(include_loopback=True)
                    if getattr(device, "isloopback", False)
                ]
                if not loopbacks:
                    raise RuntimeError("SoundCard 未找到 WASAPI 回环扬声器")
                try:
                    default_speaker = sc.default_speaker()
                    microphone = next(
                        (
                            device
                            for device in loopbacks
                            if device.name == default_speaker.name
                        ),
                        loopbacks[0],
                    )
                except Exception:
                    microphone = loopbacks[0]
                samplerate = 48000
                channels = min(2, max(1, int(microphone.channels or 1)))
                stop_event = threading.Event()
                self._audio_capture_stop = stop_event

                def capture_loop():
                    try:
                        with microphone.recorder(
                            samplerate=samplerate,
                            channels=channels,
                            blocksize=1024,
                        ) as recorder:
                            while not stop_event.is_set():
                                block = recorder.record(numframes=1024)
                                self._update_audio_spectrum(
                                    block,
                                    samplerate,
                                    np,
                                )
                    except Exception as error:
                        with self._lock:
                            self._audio_error = str(error)
                        self.log("audio_loopback_error", error=str(error))

                thread = threading.Thread(
                    target=capture_loop,
                    daemon=True,
                    name="tempo-scene-audio",
                )
                with self._lock:
                    self._audio_capture_thread = thread
                    self._audio_error = None
                thread.start()
                self.log(
                    "audio_stream_started",
                    device=getattr(microphone, "name", "loopback"),
                    backend="soundcard",
                )
                return
            except Exception as error:
                self.log("soundcard_loopback_unavailable", error=str(error))

            import _sounddevice
            import sounddevice as sd

            try:
                _sounddevice.PaWasapi_UpdateDeviceList()
            except Exception:
                pass
            devices = sd.query_devices()
            loopback_index = None
            for index, device in enumerate(devices):
                try:
                    is_loopback = bool(_sounddevice.PaWasapi_IsLoopback(index))
                except Exception:
                    is_loopback = False
                if is_loopback and int(device.get("max_input_channels") or 0) > 0:
                    loopback_index = index
                    break
            if loopback_index is None:
                raise RuntimeError("未找到 Windows WASAPI 系统音频回环设备")
            device = devices[loopback_index]
            channels = min(2, max(1, int(device.get("max_input_channels") or 1)))
            samplerate = int(float(device.get("default_samplerate") or 48000))
            def callback(indata, frames, time_info, status):
                if status:
                    self._audio_error = str(status)
                self._update_audio_spectrum(indata, samplerate, np)

            stream = sd.InputStream(
                device=loopback_index,
                channels=channels,
                samplerate=samplerate,
                blocksize=1024,
                dtype="float32",
                callback=callback,
            )
            try:
                stream.start()
            except Exception:
                stream.close()
                raise
            with self._lock:
                self._audio_stream = stream
                self._audio_error = None
            self.log("audio_stream_started", device=device.get("name"))
        except Exception as error:
            with self._lock:
                self._audio_error = str(error)
            self.log("audio_stream_error", error=str(error))

    def _update_audio_spectrum(self, data, samplerate, np):
        data = np.asarray(data, dtype=np.float32)
        if data.ndim > 1:
            mono = data.mean(axis=1)
        else:
            mono = data
        if mono.size < 32:
            return
        block = mono[-1024:] if mono.size >= 1024 else np.resize(mono, 1024)
        key = (block.size, samplerate)
        plan = self._fft_plan
        if plan is None or plan[0] != key:
            window = np.hanning(block.size)
            frequencies = np.fft.rfftfreq(block.size, 1.0 / samplerate)
            edges = np.geomspace(35.0, min(18000.0, samplerate / 2), AUDIO_BARS + 1)
            bands = [np.flatnonzero((frequencies >= edges[band]) &
                                   (frequencies < edges[band + 1]))
                     for band in range(AUDIO_BARS)]
            indices = np.linspace(0, block.size - 1, 128).astype(int)
            plan = (key, window, bands, indices)
            self._fft_plan = plan
        _, window, bands, indices = plan
        spectrum = np.abs(np.fft.rfft(block * window))
        levels = []
        for band in bands:
            power = float(np.mean(spectrum[band])) if band.size else 0.0
            db = 20.0 * math.log10(power + 1e-8)
            levels.append(_clamp((db + 62.0) / 50.0, 0.0, 1.0))
        wave = np.clip(block[indices] * 5.0, -1.0, 1.0).tolist()
        rms = float(np.sqrt(np.mean(np.square(block)) + 1e-12))
        peak = float(np.max(np.abs(block)))
        with self._lock:
            self._audio_levels = levels
            self._audio_wave = wave
            self._audio_rms_db = 20.0 * math.log10(rms + 1e-9)
            self._audio_peak_db = 20.0 * math.log10(peak + 1e-9)
            self._audio_error = None

    def _stop_audio_stream(self):
        self._audio_capture_stop.set()
        with self._lock:
            stream = self._audio_stream
            capture_thread = self._audio_capture_thread
            self._audio_stream = None
        if capture_thread is not None and capture_thread is not threading.current_thread():
            capture_thread.join(timeout=2.0)
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

    def _notification_loop(self):
        thread = threading.Thread(
            target=self._window_notification_loop,
            daemon=True,
            name="tempo-scene-window-notify",
        )
        thread.start()
        try:
            asyncio.run(self._winrt_notification_loop())
        except Exception as error:
            self._notification_status = "窗口未读检测中"
            self._notification_error = None
            self.log("winrt_notification_unavailable", error=str(error))

    async def _winrt_notification_loop(self):
        from winrt.windows.ui.notifications import NotificationKinds
        from winrt.windows.ui.notifications.management import (
            UserNotificationListener,
            UserNotificationListenerAccessStatus,
        )

        listener = UserNotificationListener.current
        status = await listener.request_access_async()
        if status != UserNotificationListenerAccessStatus.ALLOWED:
            self._notification_status = "Windows 通知权限未开启"
            return
        self._notification_status = "Windows 通知监听中"
        while not self._stop_event.is_set():
            notifications = await listener.get_notifications_async(
                NotificationKinds.TOAST
            )
            for notification in notifications:
                try:
                    app_info = notification.app_info
                    app_name = str(
                        app_info.display_info.display_name
                        if app_info and app_info.display_info
                        else ""
                    )
                    category = self._notification_category(app_name)
                    if category is None:
                        continue
                    key = (
                        category,
                        getattr(notification, "id", None),
                        str(getattr(notification, "creation_time", "")),
                    )
                    if key in self._seen_notifications:
                        continue
                    self._seen_notifications.add(key)
                    elements = (
                        notification.notification.visual.bindings[0].get_text_elements()
                    )
                    parts = [
                        str(getattr(element, "text", "") or "").strip()
                        for element in elements
                    ]
                    text = " · ".join(part for part in parts if part)
                    if text:
                        self._set_alert(category, text)
                except Exception:
                    continue
            await asyncio.sleep(2.0)

    def _window_notification_loop(self):
        user32 = ctypes.windll.user32
        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
        )
        windows = []

        def collect_window(handle, _):
            length = user32.GetWindowTextLengthW(handle)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(handle, buffer, length + 1)
                process_id = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id))
                windows.append((int(handle), process_id.value, buffer.value))
            return True

        callback = callback_type(collect_window)
        try:
            import psutil
        except Exception:
            return
        while not self._stop_event.is_set():
            windows.clear()
            user32.EnumWindows(callback, 0)
            self._check_window_notifications(windows, lambda pid: psutil.Process(pid).name())
            self._stop_event.wait(1.0)

    def _check_window_notifications(self, windows, process_name):
        baseline = {}
        names = {}
        for handle, process_id, title in windows:
            if process_id not in names:
                try:
                    names[process_id] = process_name(process_id).casefold()
                except Exception:
                    names[process_id] = ""
            category = self._process_category(names[process_id])
            if category is None:
                continue
            # QQ can expose several windows in the same process. A per-process
            # baseline makes unchanged titles appear to alternate indefinitely.
            key = (category, process_id, handle)
            previous = self._window_baseline.get(key)
            baseline[key] = title
            if previous is None or previous == title:
                continue
            if self._looks_like_unread(title) and time.monotonic() - self._last_window_alert > 2.0:
                if self._set_alert(category, self._clean_window_title(title, category)):
                    self._last_window_alert = time.monotonic()
        self._window_baseline = baseline

    @staticmethod
    def _notification_category(app_name):
        name = app_name.casefold()
        if "微信" in name or "wechat" in name or "weixin" in name:
            return "微信"
        if "qq邮箱" in name or "qqmail" in name or "qq mail" in name:
            return "QQ邮箱"
        if "qq" in name:
            return "QQ"
        return None

    @staticmethod
    def _process_category(name):
        if name in ("wechat.exe", "weixin.exe"):
            return "微信"
        if name in ("qqmail.exe", "qqmailweb.exe"):
            return "QQ邮箱"
        if name == "qq.exe":
            return "QQ"
        return None

    @staticmethod
    def _looks_like_unread(title):
        return bool(
            re.search(
                r"(\(\d+\)|\d+\s*(条|封|个)|新消息|新邮件|unread|未读)",
                title,
                flags=re.IGNORECASE,
            )
        )

    @staticmethod
    def _clean_window_title(title, category):
        cleaned = re.sub(r"^\(\d+\)\s*", "", title)
        cleaned = cleaned.replace(category, "").strip(" -—:")
        return cleaned or title

    def _fps_reader_loop(self):
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline and not self._fps_csv_path.exists():
            time.sleep(0.25)
        if not self._fps_csv_path.exists():
            self._fps_status = "等待采集数据"
            self._fps_error = "PresentMon 未生成输出文件"
            return
        self._fps_status = "采集中"
        header = None
        while not self._stop_event.is_set():
            try:
                with self._fps_csv_path.open(
                    "r", encoding="utf-8-sig", errors="replace", newline=""
                ) as handle:
                    handle.seek(self._fps_offset)
                    lines = handle.readlines()
                    self._fps_offset = handle.tell()
                for line in lines:
                    if not line.strip():
                        continue
                    row = next(csv.reader([line]))
                    if header is None:
                        if "msBetweenPresents" in row:
                            header = row
                        continue
                    try:
                        values = dict(zip(header, row))
                        frame_ms = float(values.get("msBetweenPresents") or 0)
                        app = str(values.get("Application") or "")
                        if frame_ms <= 0:
                            continue
                        key = app.casefold()
                        if key in {
                            "edifier temphub.exe",
                            "explorer.exe",
                            "dwm.exe",
                        }:
                            continue
                        with self._lock:
                            rows = self._fps_rows.setdefault(app, deque(maxlen=180))
                            rows.append((time.monotonic(), frame_ms))
                    except Exception:
                        continue
            except OSError:
                pass
            time.sleep(0.5)

    def _update_fps_from_rows(self):
        now = time.monotonic()
        with self._lock:
            samples = {app: list(rows) for app, rows in self._fps_rows.items()}
            for app, rows in samples.items():
                if not rows or now - rows[-1][0] > 10.0:
                    self._fps_rows.pop(app, None)
        best_rows = []
        best_count = 0
        for rows in samples.values():
            recent = [frame for stamp, frame in rows if now - stamp <= 2.0]
            if len(recent) > best_count:
                best_count = len(recent)
                best_rows = recent
        fps = None
        if best_count >= 4:
            ordered = sorted(best_rows)
            median = ordered[len(ordered) // 2]
            fps = 1000.0 / median if median > 0 else None
        with self._lock:
            self._metrics["fps"] = round(fps, 1) if fps else None
            self._history["fps"].append(fps)
