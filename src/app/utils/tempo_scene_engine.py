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
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen, QPolygonF


SCREEN_WIDTH = 256
SCREEN_HEIGHT = 32
AUDIO_BARS = 32
HISTORY_LENGTH = 60


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
        previous_scene = self._settings.get("scene", "lyrics")
        with self._lock:
            self._settings = dict(settings)
            scene = self._settings.get("scene", "lyrics")
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
        self._set_alert(app_name, text)

    def start_fps_capture(self):
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
        return [
            [
                1 if image.pixelColor(x, y).lightness() >= 96 else 0
                for x in range(SCREEN_WIDTH)
            ]
            for y in range(SCREEN_HEIGHT)
        ]

    def _font(self, size, family="Consolas", bold=False):
        font = QFont(family)
        font.setPixelSize(int(size))
        font.setBold(bool(bold))
        return font

    def _draw_text(self, painter, x, y, text, size=8, family="Consolas", bold=False):
        painter.setFont(self._font(size, family, bold))
        painter.drawText(QPointF(x, y), str(text))

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
        if mode == "wave":
            points = [
                QPointF(
                    index * (SCREEN_WIDTH - 1) / max(1, len(wave) - 1),
                    SCREEN_HEIGHT / 2 - float(value) * (SCREEN_HEIGHT - 5) / 2,
                )
                for index, value in enumerate(wave)
            ]
            painter.setPen(QPen(QColor("white"), 1))
            painter.drawPolyline(QPolygonF(points))
        elif mode == "vu":
            self._draw_text(painter, 4, 8, "SYSTEM AUDIO", 7, bold=True)
            self._draw_text(painter, 4, 18, "L", 8, bold=True)
            self._draw_text(painter, 4, 29, "R", 8, bold=True)
            peak = _clamp((float(audio.get("peak_db") or -80.0) + 60.0) / 60.0, 0.0, 1.0)
            rms = _clamp((float(audio.get("rms_db") or -80.0) + 60.0) / 60.0, 0.0, 1.0)
            painter.drawRect(QRectF(15, 12, 205, 5))
            painter.fillRect(QRectF(15, 12, 205 * peak, 5), QColor("white"))
            painter.drawRect(QRectF(15, 22, 205, 5))
            painter.fillRect(QRectF(15, 22, 205 * rms, 5), QColor("white"))
            self._draw_text(
                painter,
                225,
                17,
                f"{audio.get('peak_db', -80):.0f}dB",
                7,
            )
        else:
            for index in range(AUDIO_BARS):
                level = _clamp(float(levels[index] if index < len(levels) else 0.0), 0.0, 1.0)
                height = max(1, int(round(level * (SCREEN_HEIGHT - 3))))
                painter.fillRect(
                    QRectF(index * 8, SCREEN_HEIGHT - height, 6, height),
                    QColor("white"),
                )
        if error:
            painter.fillRect(QRectF(0, 0, SCREEN_WIDTH, 9), QColor("black"))
            self._draw_text(painter, 3, 8, "AUDIO OFF", 7, bold=True)

    def _draw_notifications(self, painter, settings, state):
        latest = state.get("latest") or {}
        if latest:
            app_name = str(latest.get("app") or "NOTICE").upper()
            text = str(latest.get("text") or "")
            self._draw_text(painter, 4, 10, app_name, 7, bold=True)
            font = QFont("Microsoft YaHei UI")
            font.setPixelSize(14)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                QRectF(4, 12, SCREEN_WIDTH - 8, 20),
                int(Qt.AlignmentFlag.AlignLeft.value | Qt.AlignmentFlag.AlignVCenter.value),
                text,
            )
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
        values = {
            "fps": state.get("fps"),
            "cpu": state.get("cpu"),
            "gpu": state.get("gpu"),
            "memory": state.get("memory"),
        }
        histories = state.get("history") or {}
        labels = ("FPS", "CPU", "GPU", "MEM")
        keys = ("fps", "cpu", "gpu", "memory")
        for index, (label, key) in enumerate(zip(labels, keys)):
            x = index * 64
            if index:
                painter.drawLine(x, 1, x, SCREEN_HEIGHT - 1)
            value = values[key]
            suffix = "%" if key in ("cpu", "gpu", "memory") else ""
            text = label + " " + _safe_number(value, 0) + suffix
            if key == "cpu" and state.get("cpu_temp") is not None:
                text += f" {_safe_number(state.get('cpu_temp'), 0)}C"
            if key == "gpu" and state.get("gpu_temp") is not None:
                text += f" {_safe_number(state.get('gpu_temp'), 0)}C"
            self._draw_text(painter, x + 3, 8, text[:13], 7, bold=True)
            points = histories.get(key) or []
            graph = QRectF(x + 2, 11, 60, 19)
            painter.drawRect(graph)
            if not points:
                continue
            numeric = [float(point) for point in points if point is not None]
            if not numeric:
                continue
            max_value = 100.0
            if key == "fps":
                max_value = max(60.0, max(numeric) * 1.1)
            scaled = [
                QPointF(
                    graph.left() + index_point * graph.width() / max(1, len(points) - 1),
                    graph.bottom()
                    - _clamp(float(point or 0.0) / max_value, 0.0, 1.0)
                    * (graph.height() - 2),
                )
                for index_point, point in enumerate(points)
            ]
            painter.setPen(QPen(QColor("white"), 1))
            painter.drawPolyline(QPolygonF(scaled))

    def _set_alert(self, app_name, text):
        with self._lock:
            self._alert = {
                "app": str(app_name),
                "text": str(text).strip()[:96],
                "time": time.time(),
                "until": time.monotonic() + 5.0,
            }

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
                return None, None
            usage, temperature = result.stdout.splitlines()[0].split(",")[:2]
            return float(usage.strip()), float(temperature.strip())
        except Exception:
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
            stream.start()
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
        window = np.hanning(block.size)
        spectrum = np.abs(np.fft.rfft(block * window))
        frequencies = np.fft.rfftfreq(block.size, 1.0 / samplerate)
        edges = np.geomspace(
            35.0,
            min(18000.0, samplerate / 2),
            AUDIO_BARS + 1,
        )
        levels = []
        for band in range(AUDIO_BARS):
            mask = (frequencies >= edges[band]) & (
                frequencies < edges[band + 1]
            )
            power = float(np.mean(spectrum[mask])) if np.any(mask) else 0.0
            db = 20.0 * math.log10(power + 1e-8)
            levels.append(_clamp((db + 62.0) / 50.0, 0.0, 1.0))
        indices = np.linspace(0, block.size - 1, 128).astype(int)
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
            self._audio_stream = None
            self._audio_capture_thread = None
        if stream is not None:
            try:
                stream.stop()
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
                windows.append((process_id.value, buffer.value))
            return True

        callback = callback_type(collect_window)
        try:
            import psutil
        except Exception:
            return
        while not self._stop_event.is_set():
            windows.clear()
            user32.EnumWindows(callback, 0)
            for process_id, title in windows:
                try:
                    name = psutil.Process(process_id).name().casefold()
                except Exception:
                    continue
                category = self._process_category(name)
                if category is None:
                    continue
                previous = self._window_baseline.get((category, process_id))
                self._window_baseline[(category, process_id)] = title
                if previous is None or previous == title:
                    continue
                if self._looks_like_unread(title) and time.monotonic() - self._last_window_alert > 2.0:
                    self._last_window_alert = time.monotonic()
                    self._set_alert(category, self._clean_window_title(title, category))
            self._stop_event.wait(1.0)

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
                        rows = self._fps_rows.setdefault(
                            app, deque(maxlen=180)
                        )
                        rows.append((time.monotonic(), frame_ms))
                    except Exception:
                        continue
            except OSError:
                pass
            time.sleep(0.5)

    def _update_fps_from_rows(self):
        now = time.monotonic()
        best_app = None
        best_count = 0
        for app, rows in list(self._fps_rows.items()):
            recent = [frame for stamp, frame in rows if now - stamp <= 2.0]
            if len(recent) > best_count:
                best_count = len(recent)
                best_app = app
        if best_app is None or best_count < 4:
            return
        rows = [frame for stamp, frame in self._fps_rows[best_app] if now - stamp <= 2.0]
        if not rows:
            return
        ordered = sorted(rows)
        median = ordered[len(ordered) // 2]
        fps = 1000.0 / median if median > 0 else None
        with self._lock:
            self._metrics["fps"] = round(fps, 1) if fps else None
            self._history["fps"].append(fps)
