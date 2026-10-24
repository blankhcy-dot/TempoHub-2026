"""NetEase Cloud Music lyric bridge for EDIFIER TempoHub.

This module replaces the packaged ``app.utils.pixel_lyrics_util`` entry at
import time. The original implementation remains available under
``app.utils.pixel_lyrics_util_orig`` and is used as a fallback.
"""

import base64
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import logging
from logging.handlers import RotatingFileHandler
from collections import deque
import unicodedata
import urllib.parse
import urllib.request
from bisect import bisect_right
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.utils import pixel_lyrics_util_orig as _orig
from app.utils.pixel_lyrics_util_orig import *  # noqa: F401,F403
from app.utils.pixel_lyrics_util_orig import PixelLyricsMonitor, parse_lrc_to_timeline
from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal, pyqtSlot
from app.utils.tempo_scene_engine import AUDIO_MODES, PERFORMANCE_MODES, SceneEngine
from app.utils.tempo_device_display import DeviceDisplay


_SEARCH_URL = "https://music.163.com/api/search/get/web"
_LYRIC_URL = "https://music.163.com/api/song/lyric"
_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://music.163.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}
_LOG_PATH = os.path.join(tempfile.gettempdir(), "tempo_hub_netease_lyrics.log")
_LOG_WRITER = logging.getLogger("tempo-hub-plugin")
_LOG_WRITER.setLevel(logging.INFO)
_LOG_WRITER.propagate = False
if not _LOG_WRITER.handlers:
    _log_handler = RotatingFileHandler(_LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=2,
                                      encoding="utf-8", delay=True)
    _log_handler.setFormatter(logging.Formatter("%(message)s"))
    _LOG_WRITER.addHandler(_log_handler)
_DEVICE_REPORTS = deque(maxlen=64)
_DEVICE_REPORTS_LOCK = threading.Lock()
_SETTINGS_PATH = os.path.join(
    os.environ.get("APPDATA", tempfile.gettempdir()),
    "TempoHubLyrics",
    "settings.json",
)
_SERVER_PORT = 47653
_ACTIVE_MONITOR = None
_QQ_MODEL = None
_CANVAS_MODEL = None
_CANVAS_WALLPAPER_ID = None
_LAST_RENDER = {}
_CANVAS_JOBS = queue.Queue()
_CANVAS_TIMER = None
_BRIDGE_START_LOCK = threading.Lock()
_NETEASE_PROGRESS = {
    "position": None,
    "duration": None,
    "title": "",
    "artist": "",
    "album": "",
    "track_id": "",
    "text": "",
    "updated": 0.0,
    "error": None,
}
_NETEASE_PROGRESS_LOCK = threading.Lock()
_NETEASE_PROGRESS_THREAD = None
_NETEASE_CDP_URL = "http://127.0.0.1:9222"
_CANVAS_LAST_START = 0.0
_SCENE_LAST_SEND = 0.0
_SCENE_SHOW_PENDING = True
_SCENE_RENDER_NOT_BEFORE = 0.0
_SCENE_HOME_GENERATION = 0
_SCENE_PREPARE_REQUIRED = True
_PIXEL_PROBE_MODEL = None
_PROTOCOL_LOGGING_INSTALLED = False
_SCENE_ENGINE = None
_DEVICE_DISPLAY = None
_NOTIFICATION_REFRESH = {"revision": None, "submitted_revision": None,
                         "request": None, "failures": 0, "retry_at": 0.0}
_DEVICE_OWNER = None
_EQ_PROBE_MODEL = None
_EQ_PROBE_LOCK = threading.Lock()
_NETEASE_API_LOCK = threading.Lock()
_NETEASE_API_BLOCK_UNTIL = 0.0
_NETEASE_START_LOCK = threading.Lock()
_NETEASE_START_ATTEMPTED = False
_NETEASE_MODULE_STARTED_AT = time.monotonic()
_SETTINGS_LOCK = threading.RLock()
_SETTINGS_CACHE = None
_SETTINGS_CACHE_PATH = None
_SETTINGS_STAMP = None
_SETTINGS_CHECK_AT = 0.0

_DEFAULT_SETTINGS = {
    "enabled": True,
    "scene": "lyrics",
    "audio_mode": "bars",
    "performance_mode": "tiles",
    "audio_sensitivity": 55,
    "notify_wechat": True,
    "notify_qq": True,
    "notify_qqmail": True,
    "perf_show_fps": True,
    "perf_show_cpu": True,
    "perf_show_gpu": True,
    "perf_show_memory": True,
    "sound_mode": 0,
    "font_family": "Microsoft YaHei UI",
    "font_size": 22,
    "font_weight": 600,
    "speed": 5,
    "alignment": "center",
    "line_offset_ms": 0,
    "effect": "scroll",
    "direction": "right_to_left",
}


def _log(event, **fields):
    try:
        record = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "event": event,
            **fields,
        }
        _LOG_WRITER.info(json.dumps(record, ensure_ascii=False))
    except Exception:
        pass


def _device_capability_fields(value, depth=0):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if depth > 2:
        return type(value).__name__
    result = {}
    for key in dir(value):
        if key.startswith("_") or any(word in key.casefold() for word in ("token", "password", "mac")):
            continue
        try:
            item = getattr(value, key)
            if not callable(item):
                result[key] = _device_capability_fields(item, depth + 1)
        except Exception:
            pass
    return result


def _load_settings():
    global _SETTINGS_CACHE, _SETTINGS_CACHE_PATH, _SETTINGS_STAMP, _SETTINGS_CHECK_AT
    with _SETTINGS_LOCK:
        now = time.monotonic()
        if _SETTINGS_CACHE_PATH != _SETTINGS_PATH:
            _SETTINGS_CACHE = None
            _SETTINGS_STAMP = None
            _SETTINGS_CHECK_AT = 0.0
            _SETTINGS_CACHE_PATH = _SETTINGS_PATH
        if _SETTINGS_CACHE is not None and now < _SETTINGS_CHECK_AT:
            return dict(_SETTINGS_CACHE)
        _SETTINGS_CHECK_AT = now + 1.0
        try:
            stat = os.stat(_SETTINGS_PATH)
            stamp = (stat.st_mtime_ns, stat.st_size)
            if _SETTINGS_CACHE is None or stamp != _SETTINGS_STAMP:
                with open(_SETTINGS_PATH, "r", encoding="utf-8") as file:
                    stored = json.load(file)
                if not isinstance(stored, dict):
                    raise ValueError("settings must be a JSON object")
                settings = dict(_DEFAULT_SETTINGS)
                settings.update(stored)
                _SETTINGS_CACHE = _normalize_settings(settings)
                _SETTINGS_STAMP = stamp
        except (OSError, ValueError):
            # Retain the last valid configuration during partial external edits.
            if _SETTINGS_CACHE is None:
                _SETTINGS_CACHE = dict(_DEFAULT_SETTINGS)
        return dict(_SETTINGS_CACHE)


def _normalize_settings(settings):
    for key, low, high in (("line_offset_ms", -5000, 5000),
                           ("audio_sensitivity", 20, 100), ("sound_mode", 0, 2)):
        try:
            settings[key] = max(low, min(high, int(settings.get(key, _DEFAULT_SETTINGS[key]))))
        except (ValueError, TypeError, OverflowError):
            settings[key] = _DEFAULT_SETTINGS[key]
    for key, choices in (("scene", ("lyrics", "audio", "notifications", "performance")),
                         ("audio_mode", AUDIO_MODES), ("performance_mode", PERFORMANCE_MODES)):
        if settings.get(key) not in choices:
            settings[key] = _DEFAULT_SETTINGS[key]
    settings["engine"] = "native" if settings.get("scene", "lyrics") == "lyrics" else "custom"
    return settings


def _shift_timeline(timeline, offset_ms):
    # A positive offset means showing a line earlier, as described in the UI.
    advance = float(offset_ms or 0) / 1000.0
    return [(max(0.0, float(timestamp) - advance), text) for timestamp, text in timeline]


def _save_settings(settings):
    global _SETTINGS_CACHE, _SETTINGS_STAMP, _SETTINGS_CHECK_AT
    # Serialize the complete read/merge/replace cycle across HTTP workers.
    with _SETTINGS_LOCK:
        _SETTINGS_CHECK_AT = 0.0
        merged = _load_settings()
        if isinstance(settings, dict):
            merged.update(settings)
        merged = _normalize_settings(merged)
        if merged == _SETTINGS_CACHE and os.path.isfile(_SETTINGS_PATH):
            return dict(merged)
        os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
        temporary = _SETTINGS_PATH + ".tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as file:
                json.dump(merged, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, _SETTINGS_PATH)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        _SETTINGS_CACHE = dict(merged)
        stat = os.stat(_SETTINGS_PATH)
        _SETTINGS_STAMP = (stat.st_mtime_ns, stat.st_size)
        _SETTINGS_CHECK_AT = time.monotonic() + 1.0
        if _SCENE_ENGINE is not None:
            try:
                _SCENE_ENGINE.configure(merged)
            except Exception as error:
                _log("scene_configure_error", error=str(error))
        return dict(merged)


_SCENE_ENGINE = SceneEngine(os.path.dirname(sys.executable), _log)
_SCENE_ENGINE.configure(_load_settings())


def _render_text_matrix(text, font_family, font_size, font_weight=600):
    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter

    width, height = 256, 32
    image = QImage(width, height, QImage.Format.Format_Grayscale8)
    image.fill(QColor("black"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, False)
    font = QFont(font_family or _DEFAULT_SETTINGS["font_family"])
    font.setWeight(
        QFont.Weight.DemiBold if int(font_weight) >= 500 else QFont.Weight.Normal
    )
    font.setPixelSize(max(8, min(32, int(font_size))))
    painter.setFont(font)
    painter.setPen(QColor("white"))
    metrics = QFontMetricsF(font)
    while font.pixelSize() > 8 and metrics.horizontalAdvance(text) > width:
        font.setPixelSize(font.pixelSize() - 1)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
    painter.drawText(
        QRectF(0, 0, width, height),
        int(Qt.AlignmentFlag.AlignCenter.value),
        text,
    )
    painter.end()

    matrix = [[0] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            if image.pixelColor(x, y).lightness() > 110:
                matrix[y][x] = 1

    preview_path = os.path.join(
        tempfile.gettempdir(), "tempo_hub_lyric_preview.png"
    )
    image.scaled(
        width * 4,
        height * 4,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    ).save(preview_path, "PNG")
    globals()["_LAST_RENDER"] = {
        "text": text,
        "font_family": font.family(),
        "font_size": font.pixelSize(),
        "preview_path": preview_path,
    }
    return matrix


def _parse_clock_seconds(text):
    values = []
    for match in re.finditer(r"(\d{1,3}):(\d{2})(?::(\d{2}))?", text or ""):
        first, second, third = match.groups()
        if third is None:
            values.append(int(first) * 60 + int(second))
        else:
            values.append(int(first) * 3600 + int(second) * 60 + int(third))
    return values


def _get_netease_page():
    request = urllib.request.Request(f"{_NETEASE_CDP_URL}/json/list")
    with urllib.request.urlopen(request, timeout=1.0) as response:
        targets = json.loads(response.read().decode("utf-8", "replace"))
    pages = [
        target
        for target in targets
        if target.get("type") == "page"
        and (
            "orpheus://" in str(target.get("url", ""))
            or "music.163.com" in str(target.get("url", ""))
        )
    ]
    return pages[0] if pages else None


def _read_netease_progress():
    target = _get_netease_page()
    if not target or not target.get("webSocketDebuggerUrl"):
        raise RuntimeError("网易云精确同步端口 9222 未开启")

    import websocket

    expression = """
    (async () => {
      const node = document.querySelector('.curtime-thumb');
      if (!node) return {text: '', found: false};
      const text = (node.innerText || node.textContent || '').trim();
      let track = null;
      try {
        const raw = localStorage.getItem('playingInfo');
        if (raw && typeof channel !== 'undefined' && channel.deData) {
          const decoded = await channel.deData(raw);
          const text = typeof decoded === 'string'
            ? decoded
            : (decoded?.data || String(decoded));
          const data = JSON.parse(text);
          track = data?.curTrack || data?.curPlaying?.track || null;
        }
      } catch (_) {}
      const title = String(track?.name || (
        document.querySelector('.main-title')?.innerText || ''
      )).trim();
      const artist = String(
        (track?.artists || []).map(item => item?.name || '').filter(Boolean).join(' / ')
        || (
        document.querySelector('.title-container .author')?.innerText || ''
        )
      ).trim();
      const album = String(track?.album?.name || '').trim();
      const trackId = String(track?.id || '').trim();
      const duration = Number(track?.duration) > 0
        ? Number(track.duration) / 1000
        : null;
      return {text, title, artist, album, trackId, duration, found: true};
    })()
    """
    connection = websocket.create_connection(
        target["webSocketDebuggerUrl"],
        timeout=2.5,
        suppress_origin=True,
    )
    try:
        connection.send(
            json.dumps(
                {
                    "id": 1,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": expression,
                        "returnByValue": True,
                        "awaitPromise": True,
                    },
                }
            )
        )
        while True:
            message = json.loads(connection.recv())
            if message.get("id") != 1:
                continue
            result = message.get("result", {}).get("result", {})
            value = result.get("value") or {}
            text = str(value.get("text") or "")
            values = _parse_clock_seconds(text)
            if not values:
                raise RuntimeError(f"无法从网易云播放器读取进度: {text!r}")
            return {
                "position": float(values[0]),
                "duration": (
                    float(value["duration"])
                    if value.get("duration") is not None
                    else float(values[1]) if len(values) > 1 else None
                ),
                "title": str(value.get("title") or ""),
                "artist": str(value.get("artist") or ""),
                "album": str(value.get("album") or ""),
                "track_id": str(value.get("trackId") or ""),
                "text": text,
            }
    finally:
        connection.close()


def _netease_progress_worker():
    error_logged = None
    while True:
        try:
            sample = _read_netease_progress()
            with _NETEASE_PROGRESS_LOCK:
                _NETEASE_PROGRESS.update(sample)
                _NETEASE_PROGRESS["updated"] = time.time()
                _NETEASE_PROGRESS["error"] = None
            _ensure_cdp_lyrics(sample)
            if error_logged:
                _log("netease_progress_recovered")
                error_logged = None
        except Exception as error:
            message = str(error)
            with _NETEASE_PROGRESS_LOCK:
                _NETEASE_PROGRESS["error"] = message
            if message != error_logged:
                _log("netease_progress_error", error=message)
                error_logged = message
            if time.monotonic() - _NETEASE_MODULE_STARTED_AT >= 12.0:
                _ensure_netease_running_safe()
            time.sleep(2.0)
        time.sleep(0.25)


def _start_netease_progress_bridge():
    global _NETEASE_PROGRESS_THREAD
    if _NETEASE_PROGRESS_THREAD is not None:
        return
    _NETEASE_PROGRESS_THREAD = threading.Thread(
        target=_netease_progress_worker,
        daemon=True,
        name="netease-progress-bridge",
    )
    _NETEASE_PROGRESS_THREAD.start()


def _cloudmusic_is_running():
    try:
        process_list = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq cloudmusic.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return "cloudmusic.exe" in (process_list.stdout or "").casefold()
    except Exception:
        return False


def _wait_for_netease_cdp(timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"{_NETEASE_CDP_URL}/json/list", timeout=0.8
            ):
                return True
        except Exception:
            time.sleep(0.35)
    return False


def _stop_cloudmusic_processes(executable):
    script = (
        "$target=[IO.Path]::GetFullPath($env:TEMPO_NETEASE_EXE);"
        "Get-CimInstance Win32_Process -Filter \"Name='cloudmusic.exe'\" | "
        "Where-Object { $_.ExecutablePath -and "
        "([IO.Path]::GetFullPath($_.ExecutablePath) -eq $target) } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
        "-ErrorAction SilentlyContinue }"
    )
    environment = os.environ.copy()
    environment["TEMPO_NETEASE_EXE"] = executable
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
        env=environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    deadline = time.monotonic() + 6.0
    while _cloudmusic_is_running() and time.monotonic() < deadline:
        time.sleep(0.2)


def _ensure_netease_running_safe():
    global _NETEASE_START_ATTEMPTED
    try:
        with urllib.request.urlopen(
            f"{_NETEASE_CDP_URL}/json/list", timeout=0.8
        ):
            return True
    except Exception:
        pass

    with _NETEASE_START_LOCK:
        try:
            with urllib.request.urlopen(
                f"{_NETEASE_CDP_URL}/json/list", timeout=0.8
            ):
                return True
        except Exception:
            pass

        cloudmusic_running = _cloudmusic_is_running()
        if (
            cloudmusic_running
            and _NETEASE_START_ATTEMPTED
        ):
            return False
        if (
            cloudmusic_running
            and time.monotonic() - _NETEASE_MODULE_STARTED_AT < 12.0
        ):
            return False

        candidates = [
            os.path.join(
                os.environ.get("ProgramFiles", ""),
                "NetEase",
                "CloudMusic",
                "cloudmusic.exe",
            ),
            os.path.join(
                os.environ.get("ProgramFiles(x86)", ""),
                "NetEase",
                "CloudMusic",
                "cloudmusic.exe",
            ),
        ]
        executable = next(
            (path for path in candidates if path and os.path.isfile(path)),
            None,
        )
        if executable is None:
            _log("netease_autostart_missing")
            return False

        _NETEASE_START_ATTEMPTED = True
        if cloudmusic_running:
            _log("netease_restarting_without_cdp", executable=executable)
            try:
                _stop_cloudmusic_processes(executable)
            except Exception as error:
                _log("netease_restart_stop_error", error=str(error))
                return False

        try:
            subprocess.Popen(
                [executable, "--remote-debugging-port=9222"],
                cwd=os.path.dirname(executable),
                close_fds=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            event = (
                "netease_restarted_with_cdp"
                if cloudmusic_running
                else "netease_autostarted"
            )
            _log(event, executable=executable)
        except Exception as error:
            _log("netease_autostart_error", error=str(error))
            return False
        return _wait_for_netease_cdp(12.0)


def _ensure_netease_running_async():
    threading.Thread(
        target=_ensure_netease_running_safe,
        daemon=True,
        name="netease-autostart",
    ).start()


def _netease_sample_matches(sample, title, artist):
    sample_title = _normalize_text(sample.get("title"))
    wanted_title = _normalize_text(title)
    if not sample_title or sample_title != wanted_title:
        return False
    sample_artist = _normalize_text(sample.get("artist"))
    wanted_artist = _normalize_text(artist)
    if not sample_artist or not wanted_artist:
        return True
    return (
        sample_artist == wanted_artist
        or sample_artist in wanted_artist
        or wanted_artist in sample_artist
    )


def _ensure_cdp_lyrics(sample):
    monitor = _ACTIVE_MONITOR
    title = str(sample.get("title") or "").strip()
    artist = str(sample.get("artist") or "").strip()
    track_id = str(sample.get("track_id") or "").strip()
    if monitor is None or not title:
        return
    title_key = (_normalize_text(title), _normalize_text(artist), track_id)
    now = time.time()
    if now < float(getattr(monitor, "_netease_cdp_fetching_until", 0.0) or 0.0):
        return
    if (
        title_key == getattr(monitor, "_netease_cdp_failed_key", None)
        and now < float(getattr(monitor, "_netease_cdp_retry_after", 0.0) or 0.0)
    ):
        return
    if (
        title_key == getattr(monitor, "_netease_cdp_lyric_key", None)
        and getattr(monitor, "_current_timeline", None)
    ):
        return

    monitor._netease_cdp_lyric_key = title_key
    monitor._netease_cdp_fetching_until = now + 6.0
    monitor._netease_source_active = True
    monitor._last_title = title
    monitor._last_artist = artist
    monitor._netease_album = str(sample.get("album") or "")
    monitor._netease_track_id = track_id
    monitor._current_timeline = []
    monitor._netease_timeline_times = []
    monitor._netease_base_timeline = []
    monitor._netease_line_index = None
    monitor._last_lyric_line = None
    monitor._netease_wait_until = now + 0.6

    def fetch_worker():
        try:
            monitor._fetch_and_parse_lyric_sync(
                title,
                artist,
                sample.get("duration"),
                sample,
            )
            if getattr(monitor, "_current_timeline", None):
                monitor._evt_total_duration = sample.get("duration")
                monitor._evt_position = sample.get("position")
                monitor._evt_position_time = time.time()
                monitor._netease_cdp_failed_key = None
                monitor._netease_cdp_retry_after = 0.0
            else:
                monitor._netease_cdp_failed_key = title_key
                monitor._netease_cdp_retry_after = time.time() + 90.0
        finally:
            monitor._netease_cdp_fetching_until = 0.0

    threading.Thread(
        target=fetch_worker,
        daemon=True,
        name="netease-cdp-lyrics",
    ).start()


def _netease_progress_snapshot(playing=None):
    with _NETEASE_PROGRESS_LOCK:
        sample = dict(_NETEASE_PROGRESS)
    position = sample.get("position")
    if position is None:
        return sample
    updated = float(sample.get("updated") or 0.0)
    age = max(0.0, time.time() - updated)
    sample["stale"] = age > 2.0
    if sample["stale"]:
        return sample
    if playing and age > 0.05 and not sample.get("error"):
        sample["position"] = float(position) + min(age, 1.0)
    duration = sample.get("duration")
    if duration is not None and float(duration) > 0:
        sample["position"] = min(float(duration), float(sample["position"]))
    return sample


def _get_qq_model():
    global _QQ_MODEL
    if _QQ_MODEL is not None and getattr(_QQ_MODEL, "mdevice", None) is not None:
        return _QQ_MODEL
    from app.frame.home.view.device.module_sound_box_hz.view.hz_sound_box_qq_music_model import (
        QQMusicModelCache,
    )

    model = QQMusicModelCache.get_model()
    if model is None:
        from PyQt6.QtWidgets import QApplication

        for widget in QApplication.allWidgets():
            candidate = getattr(widget, "model", None)
            if candidate is not None and candidate.__class__.__name__ == (
                "HzSoundBoxQQMusicModel"
            ):
                model = candidate
                QQMusicModelCache.set_model(candidate)
                break
    if model is not None:
        _QQ_MODEL = model
    if model is None or getattr(model, "mdevice", None) is None:
        raise RuntimeError("TempoHub device is not initialized")
    return model


def _begin_custom_eq_probe():
    global _EQ_PROBE_MODEL
    from app.frame.home.view.device.module_sound_box.view.sound_box_eq_diy_no_file_model import (
        SoundBoxEqDiyNoFileModel,
    )
    from driver.edifier_driver import ECDriver, CommandIndexType

    class ProbeModel(SoundBoxEqDiyNoFileModel):
        def __init__(self):
            super().__init__()
            self.probe_payload = None
            self.probe_event = threading.Event()
            self.probe_result = None
            self.probe_device_key = None

        def receive_data_from_usb(self, report):
            if getattr(report, "index", None) == CommandIndexType.CM_43.value:
                self.probe_payload = list(getattr(report, "payload", []) or [])
                self.probe_event.set()
            return super().receive_data_from_usb(report)

    owner = _get_device_owner()
    driver = owner.driver(ECDriver)
    model = _EQ_PROBE_MODEL
    if model is None:
        model = ProbeModel()
        _EQ_PROBE_MODEL = model
    if model.probe_device_key != id(driver):
        model.set_device(owner.mdevice)
        model.probe_device_key = id(driver)
        model.probe_result = None
    model.probe_payload = None
    model.probe_event.clear()
    model.driver(ECDriver).custom_eq_query()
    return model


def _probe_custom_eq(timeout=1.5):
    # Only the HTTP worker waits. Device listeners stay on the GUI thread so
    # queued USB signals can arrive while the caller is waiting for a result.
    from interface.client.ec_parse import custom_eq_query_analysis
    with _EQ_PROBE_LOCK:
        model = _run_device_job("eq_probe_start")
        if not model.probe_event.wait(timeout):
            return {"supported": None, "error": "设备未返回自定义 EQ 查询结果"}
        payload = list(model.probe_payload or [])
        parsed = custom_eq_query_analysis(payload)
        result = {"supported": bool(parsed), "payload": payload, "parsed": parsed}
        model.probe_result = result
        return result


def _eq_info():
    from driver.edifier_driver import ECDriver
    model = _get_device_owner()
    device = getattr(model, "mdevice", None)
    driver = model.driver(ECDriver)
    func_bean = getattr(device, "func_bean", None)
    result = {
        "product_id": getattr(device, "product_id", None),
        "vendor_id": getattr(device, "vendor_id", None),
        "eq_index": getattr(func_bean, "eq", None),
        "driver_ready": bool(driver and driver.running and not driver.is_device_deleted),
    }
    probe = _EQ_PROBE_MODEL
    result["custom_eq_probe"] = (
        dict(probe.probe_result)
        if probe is not None and probe.probe_device_key == id(driver) and probe.probe_result is not None
        else {"supported": None, "error": "自定义 EQ 能力尚未查询"}
    )
    return result


def _set_eq_preset(index):
    from driver.edifier_driver import ECDriver

    index = int(index)
    if index not in (0, 1, 2):
        raise ValueError("unsupported hardware EQ preset")
    _get_device_owner().driver(ECDriver).eq_set([index])
    return {"preset": index, "status": "queued"}


def _stop_time_tool_direct():
    from driver.edifier_driver import ECDriver

    mode_group_index = 1
    if _CANVAS_MODEL is not None:
        mode_group_index = getattr(_CANVAS_MODEL, "mode_group_index", None) or 1
    payload = [
        int(mode_group_index),
        4,
        0,
        0,
        0,
        0,
        3,
        0,
        0,
        0,
        0,
        0,
        0,
    ]
    _get_lyric_model().driver(ECDriver).hz_pixel_screen_set(payload)
    _log("scene_time_tool_stopped_directly", payload=payload)
    return {"payload": payload}


def _get_lyric_model():
    from app.frame.home.view.device.module_sound_box_hz.view.hz_sound_box_pixel_music_lyric_model import (
        HzSoundBoxPixelMusicLyricModel,
        LyricModelCache,
    )

    model = LyricModelCache.get_model()
    if model is None:
        from PyQt6.QtWidgets import QApplication

        for widget in QApplication.allWidgets():
            candidate = getattr(widget, "model", None)
            if isinstance(candidate, HzSoundBoxPixelMusicLyricModel):
                model = candidate
                LyricModelCache.set_model(candidate)
                break
    if model is None:
        model = HzSoundBoxPixelMusicLyricModel()
        model.set_device(_get_qq_model().mdevice)
        LyricModelCache.set_model(model)
        _log("lyric_model_created")
    elif getattr(model, "mdevice", None) is None:
        model.set_device(_get_qq_model().mdevice)
    return model


def _get_pixel_model():
    from PyQt6.QtWidgets import QApplication
    from app.frame.home.view.device.module_sound_box.sound_box_pixel_model import SoundBoxPixelModel
    from app.frame.home.view.device.module_sound_box_hz.sound_box_pixel_model_hz import (
        SoundBoxPixelModelHz,
    )

    for widget in QApplication.allWidgets():
        for attribute in ("model", "_model"):
            candidate = getattr(widget, attribute, None)
            if isinstance(candidate, (SoundBoxPixelModel, SoundBoxPixelModelHz)):
                return candidate
    return None


def _ensure_pixel_probe_model():
    global _PIXEL_PROBE_MODEL
    if _PIXEL_PROBE_MODEL is not None:
        return _PIXEL_PROBE_MODEL
    from app.frame.home.view.device.module_sound_box_hz.sound_box_pixel_model_hz import (
        SoundBoxPixelModelHz,
    )

    class PixelProbeModel(SoundBoxPixelModelHz):
        def receive_data_from_usb(self, report):
            result = super().receive_data_from_usb(report)
            if getattr(report, "index", None) == 257:
                _log(
                    "pixel_query_response",
                    time_tool_type=getattr(self, "time_tool_type", None),
                    time_tool_state=getattr(
                        self, "time_tool_running_state", None
                    ),
                    mode_group_index=getattr(self, "mode_group_index", None),
                    screen_switch=getattr(self, "screen_switch", None),
                )
            return result

    model = PixelProbeModel()
    model.set_device(_get_qq_model().mdevice)
    _PIXEL_PROBE_MODEL = model
    model.init_data()
    return model


def _lyric_model_state(model):
    return {
        "mode_group_index": getattr(model, "mode_group_index", None),
        "is_lyric_enabled": bool(getattr(model, "is_lyric_enabled", False)),
        "lyrics_display_mode": getattr(model, "lyrics_display_mode", None),
    }


def _force_native_lyrics(display_mode=1):
    from driver.edifier_driver import ECDriver

    model = _get_lyric_model()
    mode_group_index = getattr(model, "mode_group_index", None)
    if mode_group_index is None:
        mode_group_index = 1
    display_mode = int(display_mode or 1)
    payload = [int(mode_group_index), 3, 0, 1, display_mode]
    model.driver(ECDriver).hz_pixel_screen_set(payload)
    model.is_lyric_enabled = True
    model.lyrics_display_mode = display_mode
    _log("native_lyrics_enabled", payload=payload)
    return {"payload": payload, "model": _lyric_model_state(model)}


def _install_protocol_logging():
    global _PROTOCOL_LOGGING_INSTALLED
    if _PROTOCOL_LOGGING_INSTALLED:
        return
    from driver.edifier_driver import ECDriver
    from app.frame.home.view.device.module_sound_box_hz.view.hz_sound_box_pixel_music_lyric_model import (
        HzSoundBoxPixelMusicLyricModel,
    )

    original_send = ECDriver.edifier_send_payload
    original_report = ECDriver.edifier_set_report
    original_receive = HzSoundBoxPixelMusicLyricModel.receive_data_from_usb
    original_process = ECDriver._process_report
    original_driver_receive = ECDriver.receive_data_from_usb
    from app.frame.home.view.device.module_sound_box.view.sound_box_pixel_scene_model import SoundBoxPixelSceneModel
    original_option_select = SoundBoxPixelSceneModel.set_option_select

    def selected_scene_option(self, option_index, is_need_to_send_data=False, is_focus=False):
        if _DEVICE_DISPLAY is not None and _DEVICE_DISPLAY.is_image_request_active():
            # Our EF echoes must not trigger a second, competing vendor image
            # download through the official scene model.
            is_need_to_send_data = False
        return original_option_select(self, option_index, is_need_to_send_data, is_focus)

    def received_driver_report(self, report):
        if _CANVAS_BRIDGE is None:
            _schedule_device_bridge_start()
        if _DEVICE_DISPLAY is not None:
            _DEVICE_DISPLAY.feed_report(int(getattr(report, "index", -1)),
                                        getattr(report, "payload", []) or [], source=id(self))
        return original_driver_receive(self, report)

    def logged_process(self, data):
        try:
            from driver.common import CmdReport
            parsed = CmdReport(self.path, list(data))
            code = getattr(parsed, "code", None)
            index = int(getattr(parsed, "index", -1)) + (256 if code == 237 else 0)
            record = {"at": time.monotonic(), "index": index, "code": code,
                      "length": len(data)}
            if index in (257, 258, 259, 232, 238, 239, 23):
                record["payload"] = list(getattr(parsed, "payload", []) or [])[:64]
                # Chunk ACKs are frequent during live display. Retain them in
                # the bounded diagnostic ring without writing every ACK to disk.
                packet_ack = index == 23 and record["payload"][1:2] == [3]
                if not packet_ack or os.environ.get("TEMPOHUB_PROTOCOL_TRACE") == "1":
                    _log("device_protocol_rx", **record)
            with _DEVICE_REPORTS_LOCK:
                _DEVICE_REPORTS.append(record)
        except Exception:
            pass
        return original_process(self, data)

    def logged_send(self, index, payload=None, is_retry=False, *args, **kwargs):
        try:
            value = int(getattr(index, "value", index))
            if value in (257, 258, 259):
                _log(
                    "driver_send",
                    index=value,
                    length=len(payload or []),
                    payload=list(payload or [])[:24],
                )
        except Exception:
            pass
        result = original_send(self, index, payload, is_retry, *args, **kwargs)
        try:
            value = int(getattr(index, "value", index))
            if value in (257, 258, 259):
                _log(
                    "driver_queued",
                    index=value,
                    paused=bool(getattr(self, "is_send_pause", False)),
                    queue_size=getattr(self.send_queue, "qsize", lambda: None)(),
                    running=bool(getattr(self, "running", False)),
                )
        except Exception:
            pass
        return result

    def logged_report(self, index, payload):
        result = original_report(self, index, payload)
        try:
            value = int(getattr(index, "value", index))
            if value in (257, 258, 259):
                _log(
                    "driver_hid_result",
                    index=value,
                    success=bool(result),
                    device_path=str(getattr(self, "path", "")),
                )
        except Exception:
            pass
        return result

    def logged_receive(self, report):
        result = original_receive(self, report)
        try:
            index = int(getattr(report, "index", -1))
            if index in (257, 258):
                _log(
                    "lyric_usb",
                    index=index,
                    payload=list(getattr(report, "payload", []) or [])[:24],
                    state=_lyric_model_state(self),
                )
        except Exception:
            pass
        return result

    ECDriver.edifier_send_payload = logged_send
    ECDriver.edifier_set_report = logged_report
    ECDriver._process_report = logged_process
    ECDriver.receive_data_from_usb = received_driver_report
    SoundBoxPixelSceneModel.set_option_select = selected_scene_option
    HzSoundBoxPixelMusicLyricModel.receive_data_from_usb = logged_receive
    _PROTOCOL_LOGGING_INSTALLED = True


class _DeviceTransport:
    def __init__(self, driver, device):
        self.driver = driver
        self.key = id(driver)
        features = getattr(device, "func_bean", None)
        if getattr(device, "product_id", None) != 0xA160:
            raise RuntimeError("当前型号的像素屏协议尚未验证")
        if not getattr(getattr(features, "b25", None), "is_support_pixel_screen", False):
            raise RuntimeError("当前设备未提供像素屏功能")
        self.protocol = ("ed_canvas" if getattr(getattr(features, "b28", None),
                                               "is_support_pixel_screen_feature", False) else "legacy_ec")

    def send(self, command, payload=None):
        if command == "query":
            return self.driver.pixel_screen_query()
        if command == "screen":
            return self.driver.pixel_screen_set(payload, is_retry=False)
        if command == "image":
            return self.driver.pixel_screen_custom_image_set(payload, is_retry=False)
        if command == "text":
            return self.driver.device_text_set(payload)
        raise ValueError("未知设备操作")


def _get_device_owner():
    global _DEVICE_OWNER
    from driver.edifier_driver import ECDriver
    from PyQt6.QtWidgets import QApplication
    candidates = [_DEVICE_OWNER, _QQ_MODEL]
    if _DEVICE_OWNER is None:
        candidates.extend(getattr(widget, attribute, None)
                          for widget in QApplication.allWidgets() for attribute in ("model", "_model"))
    for owner in candidates:
        device = getattr(owner, "mdevice", None)
        if device is None or getattr(device, "product_id", None) != 0xA160:
            continue
        try:
            driver = owner.driver(ECDriver)
            if driver and driver.running and not driver.is_device_deleted:
                _DEVICE_OWNER = owner
                return owner
        except (AttributeError, RuntimeError):
            continue
    _DEVICE_OWNER = None
    raise RuntimeError("音响未连接，请检查 USB 数据线")


def _device_transport():
    from driver.edifier_driver import ECDriver
    owner = _get_device_owner()
    return _DeviceTransport(owner.driver(ECDriver), owner.mdevice)


def _device_frame(scene):
    if _SCENE_ENGINE is None:
        raise RuntimeError("显示模块正在启动，请稍后重试")
    return _SCENE_ENGINE.render_matrix(scene)


def _device_lyric_text():
    return (getattr(_ACTIVE_MONITOR, "_last_lyric_line", None)
            or getattr(_ACTIVE_MONITOR, "_last_title", None) or "等待播放音乐")


def _display_snapshot():
    if _DEVICE_DISPLAY is None:
        return {"connected": False, "pending": False, "verified": False,
                "scene": None, "phase": "starting", "last_error": "设备正在连接"}
    return _DEVICE_DISPLAY.snapshot()


def _run_device_job(kind, timeout=3.0, **fields):
    if _CANVAS_BRIDGE is None:
        raise RuntimeError("设备控制模块正在启动，请稍后重试")
    job = {"kind": kind, "done": threading.Event(), "expires_at": time.monotonic() + timeout, **fields}
    _CANVAS_JOBS.put(job)
    if not job["done"].wait(timeout):
        raise RuntimeError("设备线程未响应，请稍后重试")
    if job.get("error"):
        raise RuntimeError(job["error"])
    return job.get("result")


def _apply_device_display(settings, force=True):
    request = _run_device_job("display_submit", settings=dict(settings), force=force)
    # A prior frame can still be finishing before this request starts. Each
    # transfer has a 4.5 s bound; cover both without reporting a queued success
    # as a timeout while the newer frame is still being sent.
    if not request.done.wait(10.0):
        raise RuntimeError("音响未确认显示，请检查连接后重新应用")
    if request.error:
        raise RuntimeError(request.error)
    return request.result


def _apply_lyric_offset(offset_ms):
    monitor = _ACTIVE_MONITOR
    base = getattr(monitor, "_netease_base_timeline", None) if monitor else None
    if base:
        monitor._current_timeline = _shift_timeline(base, offset_ms)
        monitor._netease_timeline_times = [float(stamp) for stamp, _ in monitor._current_timeline]
        monitor._netease_line_index = None
        monitor._last_lyric_line = None
        monitor._locate_and_send_lyric()


class _CanvasBridge(QObject):
    request = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.request.connect(self.handle)

    def initialize(self):
        global _CANVAS_TIMER, _DEVICE_DISPLAY
        if _CANVAS_TIMER is not None:
            return
        _DEVICE_DISPLAY = DeviceDisplay(_device_transport, _device_frame, _device_lyric_text, _log)
        _CANVAS_TIMER = QTimer(self)
        _CANVAS_TIMER.setTimerType(Qt.TimerType.PreciseTimer)
        _CANVAS_TIMER.setInterval(10)
        _CANVAS_TIMER.timeout.connect(_poll_canvas_jobs)
        _CANVAS_TIMER.start()
        _log("device_control_started")

    @pyqtSlot(object)
    def handle(self, job):
        global _CANVAS_MODEL, _CANVAS_WALLPAPER_ID, _QQ_MODEL
        if job.get("kind") == "initialize":
            self.initialize()
            return
        if job.get("kind") == "display_submit":
            try:
                settings = job["settings"]
                job["result"] = _DEVICE_DISPLAY.submit(settings.get("scene", "lyrics"), settings,
                                                        force=job.get("force", True))
            except Exception as error:
                job["error"] = str(error)
            finally:
                job["done"].set()
            return
        if job.get("kind") == "apply_offset":
            try:
                _apply_lyric_offset(job["offset_ms"])
                job["result"] = True
            except Exception as error:
                job["error"] = str(error)
            finally:
                job["done"].set()
            return
        if job.get("kind") in ("eq_info", "eq_preset", "eq_probe_start", "query_device", "pixel_info", "stop_time_tool"):
            try:
                if job["kind"] == "eq_info":
                    job["result"] = _eq_info()
                elif job["kind"] == "eq_preset":
                    job["result"] = _set_eq_preset(job["index"])
                elif job["kind"] == "eq_probe_start":
                    job["result"] = _begin_custom_eq_probe()
                elif job["kind"] == "query_device":
                    _device_transport().send("query")
                    job["result"] = {"status": "query-sent"}
                elif job["kind"] == "pixel_info":
                    model = _get_pixel_model()
                    time_tool_running = getattr(model, "is_time_tool_running", None)
                    job["result"] = {
                        "found": model is not None,
                        "class": type(model).__name__ if model else None,
                        "time_tool_running": bool(time_tool_running()) if callable(time_tool_running) else None,
                        "mode_group_index": getattr(model, "mode_group_index", None),
                    }
                else:
                    if _device_transport().protocol != "ed_canvas":
                        raise RuntimeError("当前设备未提供该计时工具控制")
                    job["result"] = _stop_time_tool_direct()
            except Exception as error:
                job["error"] = str(error)
            finally:
                job["done"].set()
            return
        if job.get("kind") == "device_snapshot":
            try:
                from driver.edifier_driver import ECDriver
                model = _get_device_owner()
                driver = model.driver(ECDriver)
                from PyQt6.QtWidgets import QApplication
                from PyQt6.QtCore import QThread
                gui_thread = QApplication.instance().thread()
                if job.get("refresh"):
                    driver.pixel_screen_query()
                with _DEVICE_REPORTS_LOCK:
                    reports = list(_DEVICE_REPORTS)
                job["result"] = {
                    "driver_type": type(driver).__name__,
                    "product_id": getattr(model.mdevice, "product_id", None),
                    "capabilities": _device_capability_fields(getattr(model.mdevice, "func_bean", None)),
                    "driver_fields": sorted(getattr(driver, "__dict__", {})),
                    "driver_running": bool(getattr(driver, "running", False)),
                    "driver_paused": bool(getattr(driver, "is_send_pause", False)),
                    "driver_interval": getattr(driver, "thread_run_min_interval", None),
                    "executing_on_gui_thread": QThread.currentThread() == gui_thread,
                    "bridge_on_gui_thread": self.thread() == gui_thread,
                    "owner_on_gui_thread": model.thread() == gui_thread,
                    "display": _display_snapshot(),
                    "queue_size": getattr(getattr(driver, "send_queue", None), "qsize", lambda: None)(),
                    "retry_commands": list(getattr(driver, "send_cmd_cache", {})),
                    "canvas": {key: getattr(model, key, None) for key in (
                        "mode_group_index", "current_wallpaper_index", "wallpaper_combo_data",
                        "_is_ed03_running", "_canvas_send_offset", "_canvas_packet_index",
                        "_canvas_packets_sent_in_group", "_pending_home_wallpaper_index")},
                    "recent_reports": reports,
                }
            except Exception as error:
                job["error"] = str(error)
            finally:
                job["done"].set()
            return
        _log(
            "canvas_handle_received",
            text=job.get("text", ""),
            scene=job.get("scene"),
        )
        try:
            from app.utils.hz_canvas_bin_utils import HzCanvasBinUtils

            _ensure_canvas_model()
            if _CANVAS_MODEL._is_ed03_running:
                if time.time() - _CANVAS_LAST_START > 8.0:
                    _CANVAS_MODEL._is_ed03_running = False
                    _log("canvas_stale_send_state_reset")
                else:
                    raise RuntimeError("画布正在传输上一帧，请稍后再试")

            matrix = job.get("matrix")
            if matrix is None:
                matrix = _render_text_matrix(
                    job.get("text", ""),
                    job.get("font_family", _DEFAULT_SETTINGS["font_family"]),
                    job.get("font_size", _DEFAULT_SETTINGS["font_size"]),
                    job.get("font_weight", _DEFAULT_SETTINGS["font_weight"]),
                )
            spec = _CANVAS_MODEL.canvas_matrix_spec
            if _CANVAS_WALLPAPER_ID is None:
                file_bytes = HzCanvasBinUtils.matrix_to_bin(matrix, spec)
                _CANVAS_WALLPAPER_ID = (
                    HzCanvasBinUtils.get_wallpaper_id_from_bin(file_bytes)
                )
            _CANVAS_MODEL.pixel_canvas_send(
                matrix,
                set_home_screen=bool(job.get("show", False)),
                wallpaper_id_override=_CANVAS_WALLPAPER_ID,
            )
            globals()["_CANVAS_LAST_START"] = time.time()
            _log(
                "canvas_queued",
                text=job.get("text", ""),
                scene=job.get("scene"),
                show=bool(job.get("show", False)),
                mode_group_index=getattr(_CANVAS_MODEL, "mode_group_index", None),
                wallpaper_count=len(
                    getattr(_CANVAS_MODEL, "wallpaper_combo_data", []) or []
                ),
            )
            return True
        except Exception as error:
            _log("canvas_error", error=str(error))
            return False


_CANVAS_BRIDGE = None


def _schedule_device_bridge_start():
    """Initialize on the GUI thread even when lyrics have never been enabled."""
    global _CANVAS_BRIDGE
    from PyQt6.QtCore import QCoreApplication
    application = QCoreApplication.instance()
    if application is None:
        return False
    with _BRIDGE_START_LOCK:
        if _CANVAS_BRIDGE is None:
            bridge = _CanvasBridge()
            bridge.moveToThread(application.thread())
            _CANVAS_BRIDGE = bridge
            bridge.request.emit({"kind": "initialize"})
    return True


def _ensure_canvas_model():
    global _CANVAS_MODEL, _QQ_MODEL
    if _CANVAS_MODEL is not None:
        return _CANVAS_MODEL

    from app.frame.home.view.device.module_sound_box_hz.view.hz_sound_box_pixel_space_canvas_model import (
        HzSoundBoxPixelSpaceCanvasModel,
    )
    from app.frame.home.view.device.module_sound_box_hz.view.hz_sound_box_qq_music_model import (
        QQMusicModelCache,
    )

    qq_model = _get_qq_model()

    class _LoggedCanvasModel(HzSoundBoxPixelSpaceCanvasModel):
        def receive_data_from_usb(self, report):
            was_running = bool(getattr(self, "_is_ed03_running", False))
            try:
                _log(
                    "canvas_usb",
                    index=getattr(report, "index", None),
                    payload=list(getattr(report, "payload", []) or [])[:8],
                    sending=was_running,
                )
            except Exception:
                pass
            return super().receive_data_from_usb(report)

    _CANVAS_MODEL = _LoggedCanvasModel()
    _CANVAS_MODEL.set_device(qq_model.mdevice)
    _CANVAS_MODEL.query_pixel_setting()
    _log("canvas_model_initialized")
    return _CANVAS_MODEL


def _ensure_canvas_model_safe():
    try:
        features = getattr(_get_qq_model().mdevice, "func_bean", None)
        if not getattr(getattr(features, "b28", None), "is_support_pixel_screen_feature", False):
            return
        _ensure_canvas_model()
    except Exception as error:
        _log("canvas_preinit_error", error=str(error))


def _ensure_native_lyrics_safe():
    try:
        settings = _load_settings()
        if (
            settings.get("scene", "lyrics") == "lyrics"
            and settings.get("engine") == "native"
        ):
            if _DEVICE_DISPLAY is not None:
                _DEVICE_DISPLAY.submit("lyrics", settings, force=True)
    except Exception as error:
        _log("native_lyrics_startup_error", error=str(error))


def _dispatch_canvas(job):
    _CANVAS_JOBS.put(job)
    _log("canvas_dispatch_queued", text=job.get("text", ""))


def _prepare_scene_display():
    global _SCENE_LAST_SEND, _SCENE_SHOW_PENDING, _SCENE_RENDER_NOT_BEFORE
    global _SCENE_HOME_GENERATION
    _SCENE_LAST_SEND = 0.0
    _SCENE_SHOW_PENDING = True
    _SCENE_RENDER_NOT_BEFORE = time.time() + 0.8
    try:
        pixel_model = _get_pixel_model()
        if pixel_model is None:
            _log("scene_pixel_model_missing")
            pixel_model = _ensure_pixel_probe_model()
            QTimer.singleShot(1400, _finish_pixel_probe)
            _stop_time_tool_direct()
        else:
            running = pixel_model.is_time_tool_running()
            _log("scene_pixel_model_found", time_tool_running=running)
            if running:
                pixel_model.send_end_time_tool()
                _log("scene_stopped_time_tool")
    except Exception as error:
        _log("scene_time_tool_stop_error", error=str(error))
    try:
        from driver.edifier_driver import ECDriver

        _get_lyric_model().driver(ECDriver).hz_pixel_screen_set([1, 0, 0])
        _log("scene_pixel_screen_enabled")
    except Exception as error:
        _log("scene_pixel_screen_enable_error", error=str(error))
    if _CANVAS_MODEL is not None:
        try:
            _CANVAS_MODEL._is_ed03_running = False
            reset = getattr(_CANVAS_MODEL, "_reset_canvas_send_state", None)
            if reset is not None:
                reset()
        except Exception as error:
            _log("canvas_scene_reset_error", error=str(error))
    _SCENE_HOME_GENERATION += 1
    generation = _SCENE_HOME_GENERATION

    for delay in (3.0, 8.0, 15.0, 22.0):
        QTimer.singleShot(
            int(delay * 1000),
            lambda attempt=delay: _commit_scene_home(generation, attempt),
        )


def _finish_pixel_probe():
    model = _PIXEL_PROBE_MODEL
    if model is None:
        return
    try:
        try:
            running = bool(model.is_time_tool_running())
        except Exception:
            running = False
        _log(
            "pixel_probe_finished",
            time_tool_running=running,
            time_tool_type=getattr(model, "time_tool_type", None),
            time_tool_tone=getattr(model, "time_tool_tone_switch", None),
            time_tool_mode=getattr(model, "time_tool_time_mode", None),
            mode_group_index=getattr(model, "mode_group_index", None),
        )
        if running:
            model.send_end_time_tool()
            _log("scene_stopped_time_tool", mode="probe")
    except Exception as error:
        _log("pixel_probe_error", error=str(error))


def _commit_scene_home(generation, attempt):
    if generation != _SCENE_HOME_GENERATION:
        return
    try:
        from driver.edifier_driver import ECDriver

        mode_group = 1
        if _CANVAS_MODEL is not None:
            mode_group = getattr(_CANVAS_MODEL, "mode_group_index", None) or 1
        _get_lyric_model().driver(ECDriver).hz_pixel_wallpaper_set(
            [int(mode_group), 2, 0]
        )
        _log(
            "scene_home_commit_sent",
            attempt=attempt,
            mode_group_index=mode_group,
        )
    except Exception as error:
        _log("scene_home_commit_error", error=str(error))


def _cancel_scene_home_commit():
    global _SCENE_HOME_GENERATION, _SCENE_SHOW_PENDING, _SCENE_PREPARE_REQUIRED
    _SCENE_HOME_GENERATION += 1
    _SCENE_SHOW_PENDING = False
    _SCENE_PREPARE_REQUIRED = False


def _request_scene_display():
    global _SCENE_PREPARE_REQUIRED
    _SCENE_PREPARE_REQUIRED = True


def _refresh_notification_display(settings, display):
    if _SCENE_ENGINE is None:
        return
    notification = _SCENE_ENGINE.notification_display_state()
    revision = notification["revision"]
    refresh = _NOTIFICATION_REFRESH
    request = refresh["request"]
    if request is not None and request.done.is_set():
        if request.error:
            refresh["failures"] += 1
            refresh["retry_at"] = time.monotonic() + min(8.0, 2.0 ** refresh["failures"])
        else:
            refresh["revision"] = refresh["submitted_revision"]
            refresh["failures"] = 0
        refresh["request"] = None
    if settings.get("scene") != "notifications" or not settings.get("enabled", True):
        refresh["revision"] = None
        refresh["failures"] = 0
        return
    if not display.get("connected"):
        refresh["revision"] = None
        refresh["failures"] = 0
        refresh["retry_at"] = 0.0
        return
    if revision != refresh["submitted_revision"]:
        refresh["failures"] = 0
        refresh["retry_at"] = 0.0
    if display.get("scene") != "notifications":
        refresh["revision"] = None
    if (refresh["request"] is None and revision != refresh["revision"]
            and not display.get("pending") and refresh["failures"] < 3
            and time.monotonic() >= refresh["retry_at"]):
        refresh["submitted_revision"] = revision
        refresh["request"] = _DEVICE_DISPLAY.submit("notifications", settings, force=False)


def _poll_canvas_jobs():
    if _CANVAS_BRIDGE is None or _DEVICE_DISPLAY is None:
        return
    while True:
        try:
            job = _CANVAS_JOBS.get_nowait()
        except queue.Empty:
            break
        if time.monotonic() > job.get("expires_at", float("inf")):
            job["error"] = "设备操作已超时，未执行过期请求"
            if job.get("done") is not None:
                job["done"].set()
            continue
        _CANVAS_BRIDGE.handle(job)
    try:
        settings = _load_settings()
        # Refresh is owned by the backend, independently of the preview window.
        # The controller starts the next frame only after the current frame is
        # acknowledged, and explicit scene requests take priority over refresh.
        _DEVICE_DISPLAY.tick(settings, auto_refresh=settings.get("scene") in ("audio", "performance"))
        _refresh_notification_display(settings, _DEVICE_DISPLAY.snapshot())
        interval = 10 if _DEVICE_DISPLAY.snapshot()["pending"] else 50
        if _CANVAS_TIMER.interval() != interval:
            _CANVAS_TIMER.setInterval(interval)
    except Exception as error:
        _log("device_tick_error", error=str(error))


class _LocalApiHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def setup(self):
        super().setup()
        self.connection.settimeout(5.0)

    def do_GET(self):
        if self.path.partition("?")[0] == "/api/device":
            try:
                self._send(200, _run_device_job("device_snapshot", refresh="refresh=1" in self.path))
            except Exception as error:
                self._send(503, {"error": str(error)})
            return
        if self.path == "/api/settings":
            self._send(200, _load_settings())
            return
        if self.path == "/api/state":
            monitor = _ACTIVE_MONITOR
            progress = _netease_progress_snapshot(
                bool(getattr(monitor, "_evt_is_playing", None))
            )
            display = _display_snapshot()
            lyric_model = display.get("lyrics", {})
            self._send(
                200,
                {
                    "running": bool(monitor and getattr(monitor, "_running", False)),
                    "scene": _load_settings().get("scene", "lyrics"),
                    "song": getattr(monitor, "_last_title", None) if monitor else None,
                    "artist": getattr(monitor, "_last_artist", None) if monitor else None,
                    "listen_mode": getattr(monitor, "_listen_mode", None) if monitor else None,
                    "timeline_count": len(getattr(monitor, "_current_timeline", []) or []),
                    "last_lyric": getattr(monitor, "_last_lyric_line", None) if monitor else None,
                    "position_seconds": (
                        _session_position_seconds(monitor) if monitor else None
                    ),
                    "netease_progress": progress,
                    "lyric_model": lyric_model,
                    "display": display,
                    "is_playing": (
                        getattr(monitor, "_evt_is_playing", None) if monitor else None
                    ),
                    "last_render": _LAST_RENDER,
                    "canvas_ready": display.get("connected", False),
                    "canvas_sending": display.get("pending", False),
                    "canvas_wallpaper_count": len(
                        getattr(_CANVAS_MODEL, "wallpaper_combo_data", []) or []
                    ),
                    "canvas_packet_index": getattr(
                        _CANVAS_MODEL, "_canvas_packet_index", None
                    ),
                    "widgets": (
                        _SCENE_ENGINE.snapshot()
                        if _SCENE_ENGINE is not None
                        else {}
                    ),
                },
            )
            return
        if self.path == "/api/scene-frame":
            settings = _load_settings()
            scene = str(settings.get("scene", "lyrics"))
            matrix = (
                _SCENE_ENGINE.render_matrix(scene)
                if _SCENE_ENGINE is not None
                else None
            )
            packed = bytearray()
            if matrix:
                for row in matrix:
                    for start in range(0, len(row), 8):
                        value = 0
                        for bit in range(8):
                            if start + bit < len(row) and row[start + bit]:
                                value |= 1 << (7 - bit)
                        packed.append(value)
            self._send(
                200,
                {
                    "scene": scene,
                    "audio_mode": settings.get("audio_mode", "bars"),
                    "performance_mode": settings.get("performance_mode", "tiles"),
                    "width": 256,
                    "height": 32,
                    "matrix": base64.b64encode(packed).decode("ascii"),
                },
            )
            return
        if self.path == "/api/eq/probe":
            try:
                self._send(200, _probe_custom_eq())
            except Exception as error:
                self._send(500, {"error": str(error)})
            return
        if self.path == "/api/pixel-model":
            try:
                self._send(200, _run_device_job("pixel_info"))
            except Exception as error:
                self._send(500, {"error": str(error)})
            return
        if self.path == "/api/pixel/end-time-tool":
            try:
                self._send(202, _run_device_job("stop_time_tool"))
            except Exception as error:
                self._send(500, {"error": str(error)})
            return
        if self.path == "/api/eq/info":
            try:
                self._send(200, _run_device_job("eq_info"))
            except Exception as error:
                self._send(500, {"error": str(error)})
            return
        if self.path == "/api/diagnose":
            try:
                self._send(
                    200,
                    {
                        "lyric_model": _display_snapshot().get("lyrics", {}),
                        "display": _display_snapshot(),
                        "progress": _netease_progress_snapshot(
                            bool(
                                getattr(_ACTIVE_MONITOR, "_evt_is_playing", None)
                            )
                        ),
                    },
                )
            except Exception as error:
                self._send(500, {"error": str(error)})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 64 * 1024:
                self._send(413, {"error": "request body must be 1 to 65536 bytes"})
                return
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("expected JSON object")
        except (ValueError, UnicodeError, OSError):
            self._send(400, {"error": "invalid json"})
            return

        if self.path == "/api/settings":
            try:
                previous_settings = _load_settings()
                previous_scene = previous_settings.get("scene", "lyrics")
                reapply_device = bool(payload.get("reapply_device", True))
                stored_payload = {
                    key: value
                    for key, value in payload.items()
                    if key != "reapply_device"
                }
                settings = _save_settings(stored_payload)
                scene = str(settings.get("scene", "lyrics"))
                if reapply_device and settings == previous_settings and _SCENE_ENGINE is not None:
                    _SCENE_ENGINE.configure(settings)
                if settings.get("line_offset_ms") != previous_settings.get("line_offset_ms"):
                    _run_device_job("apply_offset", offset_ms=settings.get("line_offset_ms", 0))
                display_changed = any(settings.get(key) != previous_settings.get(key)
                                      for key in stored_payload if key not in ("line_offset_ms", "sound_mode"))
                apply_display = settings.get("enabled", True) and (reapply_device or display_changed)
                result = {"settings": settings, "applied": bool(apply_display)}
                if apply_display:
                    result["display"] = _apply_device_display(settings, force=reapply_device or previous_scene != scene)
                else:
                    result["display"] = _display_snapshot()
                self._send(200, result)
            except Exception as error:
                self._send(500, {"error": str(error)})
            return
        if self.path == "/api/test-canvas":
            try:
                settings = dict(_load_settings(), scene=payload.get("scene", "performance"))
                result = _apply_device_display(settings)
                self._send(200, {"display": result})
            except Exception as error:
                self._send(500, {"error": str(error)})
            return
        if self.path == "/api/restore-native":
            try:
                settings = _save_settings({"engine": "native", "scene": "lyrics"})
                self._send(
                    200,
                    {
                        "status": "native",
                        "settings": settings,
                        "display": _apply_device_display(settings),
                        "applied": True,
                    },
                )
            except Exception as error:
                self._send(500, {"error": str(error)})
            return
        if self.path == "/api/diagnose":
            try:
                self._send(202, _run_device_job("query_device"))
            except Exception as error:
                self._send(500, {"error": str(error)})
            return
        if self.path == "/api/ensure-netease":
            ready = _ensure_netease_running_safe()
            self._send(
                200,
                {
                    "ready": bool(ready),
                    "error": (
                        None
                        if ready
                        else "网易云同步端口未就绪"
                    ),
                },
            )
            return
        if self.path == "/api/notifications/test":
            try:
                incoming_settings = payload.get("settings", {})
                if not isinstance(incoming_settings, dict):
                    raise ValueError("通知设置必须为 JSON 对象")
                previous = _load_settings()
                updates = {key: value for key, value in incoming_settings.items() if key != "reapply_device"}
                settings = _save_settings(dict(updates, scene="notifications", enabled=True))
                if settings.get("line_offset_ms") != previous.get("line_offset_ms"):
                    _run_device_job("apply_offset", offset_ms=settings.get("line_offset_ms", 0))
                _SCENE_ENGINE.trigger_notification(
                    str(payload.get("app") or "微信"),
                    str(payload.get("text") or "这是一条测试消息"),
                )
                display = _apply_device_display(settings)
                self._send(200, {"status": "shown", "settings": settings, "applied": True, "display": display})
            except Exception as error:
                self._send(500, {"error": str(error)})
            return
        if self.path == "/api/performance/start-fps":
            try:
                self._send(202, _SCENE_ENGINE.start_fps_capture())
            except Exception as error:
                self._send(500, {"error": str(error)})
            return
        if self.path == "/api/eq/preset":
            try:
                index = int(payload.get("index", 0))
                result = _run_device_job("eq_preset", index=index)
                _save_settings({"sound_mode": index})
                self._send(202, result)
            except Exception as error:
                self._send(500, {"error": str(error)})
            return
        self._send(404, {"error": "not found"})


def _start_local_api():
    try:
        server = ThreadingHTTPServer(("127.0.0.1", _SERVER_PORT), _LocalApiHandler)
    except Exception as error:
        _log("api_start_error", error=str(error))
        return
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()


def _http_json(url, timeout=8):
    global _NETEASE_API_BLOCK_UNTIL
    is_search_request = url.startswith(_SEARCH_URL)
    if is_search_request:
        with _NETEASE_API_LOCK:
            blocked_until = _NETEASE_API_BLOCK_UNTIL
        if time.time() < blocked_until:
            raise RuntimeError("网易云歌词接口暂时限流，稍后自动重试")
    request = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", "replace")
    data = json.loads(body)
    if is_search_request and int(data.get("code", 200) or 200) in (
        405,
        429,
    ):
        with _NETEASE_API_LOCK:
            _NETEASE_API_BLOCK_UNTIL = max(
                _NETEASE_API_BLOCK_UNTIL,
                time.time() + 90.0,
            )
        _log("netease_rate_limited", code=data.get("code"))
        raise RuntimeError("网易云歌词接口限流，已暂停请求 90 秒")
    return data


def _normalize_text(value):
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    value = value.replace("’", "'").replace("‘", "'")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _normalize_title(value):
    value = _normalize_text(value)
    value = re.sub(r"\s*[\(\[\{].*?[\)\]\}]\s*$", "", value)
    return value.strip()


def _artist_parts(value):
    parts = re.split(r"[,/&、+;；]|\bfeat\.?\b|\bft\.?\b", _normalize_text(value))
    return [part.strip() for part in parts if part.strip()]


def _artist_match(artist, candidate_artists):
    wanted = _artist_parts(artist)
    if not wanted:
        return 0.0
    candidate = _normalize_text(" ".join(candidate_artists))
    if not candidate:
        return 0.0
    if any(part and (part in candidate or candidate in part) for part in wanted):
        return 1.0
    return 0.0


def _duration_delta(duration, candidate_milliseconds):
    try:
        candidate_seconds = float(candidate_milliseconds) / 1000.0
        if duration is not None and float(duration) > 0:
            return abs(float(duration) - candidate_seconds)
    except (TypeError, ValueError):
        return None
    return None


def _score_candidate(title, artist, duration, song, album=""):
    song_title = _normalize_title(song.get("name", ""))
    wanted_title = _normalize_title(title)
    if not song_title or not wanted_title:
        return None

    if song_title == wanted_title:
        title_score = 2.0
    elif wanted_title in song_title or song_title in wanted_title:
        title_score = 1.0
    else:
        return None

    artists = [
        item.get("name", "")
        for item in (song.get("artists") or song.get("ar") or [])
        if isinstance(item, dict)
    ]
    artist_score = _artist_match(artist, artists)
    candidate_album = ""
    album_obj = song.get("album") or song.get("al") or {}
    if isinstance(album_obj, dict):
        candidate_album = _normalize_text(album_obj.get("name", ""))
    wanted_album = _normalize_text(album)
    album_score = 1.0 if wanted_album and candidate_album == wanted_album else 0.0
    delta = _duration_delta(duration, song.get("duration"))
    duration_score = 0.0
    if delta is not None:
        if delta > 20.0:
            return None
        duration_score = max(0.0, 1.0 - delta / 20.0)

    # Require either a matching artist or a close duration for less exact
    # titles. Exact title matches from the search endpoint are still useful
    # when the platform omits one of those fields.
    if title_score < 2.0 and artist_score == 0.0 and delta is None:
        return None

    return (
        artist_score * 10.0
        + title_score * 5.0
        + album_score * 4.0
        + duration_score
        - (delta or 0.0) / 200.0
        + _version_penalty(title, song_title, candidate_album)
    )


def _version_penalty(title, song_title, candidate_album):
    wanted = _normalize_text(title)
    marker_text = f"{song_title} {candidate_album}"
    markers = (
        "live",
        "remix",
        "instrumental",
        "karaoke",
        "cover",
        "现场",
        "翻唱",
        "伴奏",
        "纯音乐",
        "dj",
    )
    penalty = 0.0
    for marker in markers:
        if marker in marker_text and marker not in wanted:
            penalty -= 4.0
    return penalty


def _find_netease_song(title, artist, duration, album=""):
    query = " ".join(part for part in (title, artist) if part).strip()
    if not query:
        return None

    params = urllib.parse.urlencode(
        {"s": query, "type": 1, "limit": 30, "offset": 0}
    )
    data = _http_json(f"{_SEARCH_URL}?{params}")
    if data.get("code") != 200:
        return None

    songs = (data.get("result") or {}).get("songs") or []
    scored = []
    for song in songs:
        score = _score_candidate(title, artist, duration, song, album)
        if score is not None:
            scored.append((score, song))
    if not scored:
        return None

    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _fetch_netease_lyric(title, artist, duration, album=""):
    song = _find_netease_song(title, artist, duration, album)
    if not song or song.get("id") is None:
        return None

    params = urllib.parse.urlencode(
        {"id": song["id"], "lv": -1, "kv": -1, "tv": -1}
    )
    data = _http_json(f"{_LYRIC_URL}?{params}")
    if data.get("code") != 200:
        return None

    lyric = (data.get("lrc") or {}).get("lyric") or ""
    if not lyric.strip() or (data.get("nolyric") or data.get("uncollected")):
        return None
    return lyric, song


def _fetch_netease_lyric_by_id(track_id, title="", artist="", duration=None):
    if not track_id:
        return None
    params = urllib.parse.urlencode(
        {"id": track_id, "lv": -1, "kv": -1, "tv": -1}
    )
    data = _http_json(f"{_LYRIC_URL}?{params}")
    if data.get("code") != 200:
        return None
    lyric = (data.get("lrc") or {}).get("lyric") or ""
    if not lyric.strip():
        lyric = (data.get("tlyric") or {}).get("lyric") or ""
    if not lyric.strip() or data.get("nolyric") or data.get("uncollected"):
        return None
    return lyric, {
        "id": track_id,
        "name": title,
        "duration": float(duration) * 1000 if duration else None,
        "artists": [{"name": artist}] if artist else [],
    }


_original_handle_media_change = PixelLyricsMonitor._handle_media_change
_original_fetch_sync = PixelLyricsMonitor._fetch_and_parse_lyric_sync
_original_start = PixelLyricsMonitor.start
_original_locate_and_send = PixelLyricsMonitor._locate_and_send_lyric


def _session_position_seconds(self):
    if getattr(self, "_netease_source_active", False):
        progress = _netease_progress_snapshot(
            bool(getattr(self, "_evt_is_playing", None))
        )
        if progress.get("position") is not None:
            return float(progress["position"])
    session = getattr(self, "_winrt_session", None)
    if session is not None:
        try:
            position = session.get_timeline_properties().position
            ticks = getattr(position, "duration", None)
            if ticks is not None:
                return max(0.0, float(ticks) / 10_000_000.0)
        except Exception:
            pass
    position = getattr(self, "_evt_position", None)
    if position is None:
        return None
    position = max(0.0, float(position))
    if getattr(self, "_evt_is_playing", False):
        updated = float(getattr(self, "_evt_position_time", 0.0) or 0.0)
        if updated > 0:
            position += max(0.0, min(2.0, time.time() - updated))
    return position


def _locate_and_send_lyric(self, provided_position=None):
    timeline = getattr(self, "_current_timeline", None)
    if _load_settings().get("scene", "lyrics") != "lyrics":
        return None
    if not timeline:
        return None
    if getattr(self, "_netease_source_active", False):
        wait_until = float(getattr(self, "_netease_wait_until", 0.0) or 0.0)
        if time.time() < wait_until:
            return None
        progress = _netease_progress_snapshot(
            bool(getattr(self, "_evt_is_playing", None))
        )
        if progress.get("position") is not None:
            current_seconds = float(progress["position"])
            self._evt_position = current_seconds
            self._evt_position_time = time.time()
            if progress.get("duration"):
                self._evt_total_duration = float(progress["duration"])
            times = getattr(self, "_netease_timeline_times", None)
            if times is None or len(times) != len(timeline):
                times = [float(item[0]) for item in timeline]
                self._netease_timeline_times = times

            target_index = bisect_right(times, current_seconds) - 1
            held_index = getattr(self, "_netease_line_index", None)
            if held_index is not None and 0 <= held_index < len(timeline):
                held_time = times[held_index]
                next_time = (
                    times[held_index + 1]
                    if held_index + 1 < len(times)
                    else None
                )
                # Keep the current line around an exact boundary.  Without
                # this small hold, a one-second DOM clock can flip A/B/A.
                if (
                    current_seconds >= held_time - 0.45
                    and (
                        next_time is None
                        or current_seconds < next_time + 0.03
                    )
                ):
                    target_index = held_index

            if target_index < 0:
                return None
            self._netease_line_index = target_index
            current_line = timeline[target_index][1]
            if current_line and current_line != getattr(
                self, "_last_lyric_line", None
            ):
                self._last_lyric_line = current_line
                _log(
                    "lyric_line_changed",
                    position=round(current_seconds, 3),
                    line_index=target_index,
                    text=current_line,
                )
                callback = getattr(self, "_on_lyric_changed", None)
                if callback is not None:
                    try:
                        callback(current_line)
                    except Exception as error:
                        _log("lyric_callback_error", error=str(error))
            return current_line
    return _original_locate_and_send(self, provided_position)


def _start(self):
    global _ACTIVE_MONITOR, _QQ_MODEL
    _ACTIVE_MONITOR = self
    callback_owner = getattr(getattr(self, "_on_lyric_changed", None), "__self__", None)
    if callback_owner is not None:
        _QQ_MODEL = callback_owner
        _patch_qq_lyric_callback(callback_owner)
        self._on_lyric_changed = type(callback_owner)._on_lyric_text_changed.__get__(
            callback_owner, type(callback_owner)
        )
    _schedule_device_bridge_start()
    return _original_start(self)


def _patch_qq_lyric_callback(owner):
    model_class = type(owner)
    if getattr(model_class, "_netease_canvas_callback_patch", False):
        return
    original = model_class._on_lyric_text_changed

    def patched(self, lyric_line):
        settings = _load_settings()
        if settings.get("scene", "lyrics") != "lyrics":
            return
        if (
            settings.get("enabled", True)
            and settings.get("engine") == "custom"
            and lyric_line
        ):
            _dispatch_canvas(
                {
                    "text": lyric_line,
                    "font_family": settings.get(
                        "font_family", _DEFAULT_SETTINGS["font_family"]
                    ),
                    "font_size": settings.get(
                        "font_size", _DEFAULT_SETTINGS["font_size"]
                    ),
                    "font_weight": settings.get(
                        "font_weight", _DEFAULT_SETTINGS["font_weight"]
                    ),
                    "speed": settings.get("speed", _DEFAULT_SETTINGS["speed"]),
                    "alignment": settings.get(
                        "alignment", _DEFAULT_SETTINGS["alignment"]
                    ),
                    "direction": settings.get(
                        "direction", _DEFAULT_SETTINGS["direction"]
                    ),
                    "show": False,
                }
            )
            return
        return original(self, lyric_line)

    model_class._on_lyric_text_changed = patched
    model_class._netease_canvas_callback_patch = True


async def _handle_media_change(self):
    session = getattr(self, "_winrt_session", None)
    app_id = str(getattr(session, "source_app_user_model_id", "") or "").casefold()
    self._netease_source_active = "cloudmusic" in app_id
    if self._netease_source_active:
        _log("netease_session", app_id=app_id)
        try:
            properties = await session.try_get_media_properties_async()
            title = str(getattr(properties, "title", "") or "")
            artist = str(getattr(properties, "artist", "") or "")
            previous_title = str(getattr(self, "_last_title", "") or "")
            previous_artist = str(getattr(self, "_last_artist", "") or "")
            title_changed = _normalize_text(title) != _normalize_text(
                previous_title
            )
            artist_changed = _normalize_text(artist) != _normalize_text(
                previous_artist
            )
            if title and (title_changed or artist_changed):
                self._current_timeline = []
                self._netease_timeline_times = []
                self._netease_base_timeline = []
                self._netease_line_index = None
                self._last_lyric_line = None
                self._netease_wait_until = time.time() + 1.0
                _log(
                    "netease_song_switch_hold",
                    title=title,
                    artist=artist,
                )
            self._netease_album = str(
                getattr(properties, "album_title", "") or ""
            )
        except Exception:
            self._netease_album = ""
    return await _original_handle_media_change(self)


def _fetch_and_parse_lyric_sync(
    self,
    title,
    artist,
    duration,
    netease_sample=None,
):
    if getattr(self, "_netease_source_active", False):
        try:
            sample = netease_sample or _netease_progress_snapshot()
            if not _netease_sample_matches(sample, title, artist):
                _log(
                    "netease_stale_media_skipped",
                    title=title,
                    artist=artist,
                    sample_title=sample.get("title"),
                    sample_artist=sample.get("artist"),
                )
                return None
            track_id = str(sample.get("track_id") or "")
            self._netease_track_id = track_id
            if track_id:
                result = _fetch_netease_lyric_by_id(
                    track_id,
                    title,
                    artist,
                    duration,
                )
            else:
                result = _fetch_netease_lyric(
                    title,
                    artist,
                    duration,
                    getattr(self, "_netease_album", ""),
                )
            if result:
                lyric, _song = result
                current_sample = _netease_progress_snapshot()
                if (
                    not _netease_sample_matches(current_sample, title, artist)
                    or str(current_sample.get("track_id") or "") != track_id
                ):
                    _log(
                        "netease_stale_lyrics_discarded",
                        title=title,
                        artist=artist,
                        requested_track_id=track_id,
                        current_track_id=current_sample.get("track_id"),
                        current_title=current_sample.get("title"),
                    )
                    return None
                timeline = parse_lrc_to_timeline(lyric)
                if timeline:
                    self._netease_base_timeline = list(timeline)
                    self._netease_line_index = None
                    self._netease_wait_until = time.time() + 0.55
                    timeline = _shift_timeline(
                        timeline, _load_settings().get("line_offset_ms", 0)
                    )
                    self._current_timeline = timeline
                    self._netease_timeline_times = [
                        float(timestamp) for timestamp, _ in timeline
                    ]
                    self._last_lyric_line = None
                    try:
                        self._song_play_time = float(_song.get("duration")) / 1000.0
                    except (TypeError, ValueError):
                        self._song_play_time = None
                    _log(
                        "netease_lyrics_ready",
                        title=title,
                        artist=artist,
                        matched_song=_song.get("name"),
                        timeline_count=len(timeline),
                    )
                    return timeline
                _log("netease_empty_timeline", title=title, artist=artist)
            else:
                _log("netease_no_match", title=title, artist=artist)
        except Exception as error:
            # Preserve the original app's behavior when the public lyrics
            # endpoint is unavailable or the track cannot be matched.
            _log("netease_error", title=title, artist=artist, error=str(error))

    return _original_fetch_sync(self, title, artist, duration)


PixelLyricsMonitor._handle_media_change = _handle_media_change
PixelLyricsMonitor._fetch_and_parse_lyric_sync = _fetch_and_parse_lyric_sync
PixelLyricsMonitor.start = _start
PixelLyricsMonitor._locate_and_send_lyric = _locate_and_send_lyric

_install_protocol_logging()
_schedule_device_bridge_start()
_start_netease_progress_bridge()
_start_local_api()
