"""NetEase Cloud Music lyric bridge for EDIFIER TempoHub.

This module replaces the packaged ``app.utils.pixel_lyrics_util`` entry at
import time. The original implementation remains available under
``app.utils.pixel_lyrics_util_orig`` and is used as a fallback.
"""

import json
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
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
_PROTOCOL_LOGGING_INSTALLED = False
_NETEASE_API_LOCK = threading.Lock()
_NETEASE_API_BLOCK_UNTIL = 0.0
_NETEASE_START_LOCK = threading.Lock()

_DEFAULT_SETTINGS = {
    "enabled": True,
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
        with open(_LOG_PATH, "a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _load_settings():
    settings = dict(_DEFAULT_SETTINGS)
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as file:
            stored = json.load(file)
        if isinstance(stored, dict):
            settings.update(stored)
    except Exception:
        pass
    return settings


def _save_settings(settings):
    merged = _load_settings()
    if isinstance(settings, dict):
        merged.update(settings)
    os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
    temporary = _SETTINGS_PATH + ".tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(merged, file, ensure_ascii=False, indent=2)
    os.replace(temporary, _SETTINGS_PATH)
    return merged


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


def _ensure_netease_running_safe():
    try:
        with urllib.request.urlopen(
            f"{_NETEASE_CDP_URL}/json/list", timeout=0.8
        ):
            return
    except Exception:
        pass

    with _NETEASE_START_LOCK:
        try:
            process_list = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq cloudmusic.exe", "/NH"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if "cloudmusic.exe" in (process_list.stdout or "").casefold():
                return
        except Exception:
            return

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
            return
        try:
            subprocess.Popen(
                [executable, "--remote-debugging-port=9222"],
                cwd=os.path.dirname(executable),
                close_fds=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            _log("netease_autostarted", executable=executable)
        except Exception as error:
            _log("netease_autostart_error", error=str(error))


def _ensure_cdp_lyrics(sample):
    monitor = _ACTIVE_MONITOR
    title = str(sample.get("title") or "").strip()
    artist = str(sample.get("artist") or "").strip()
    if monitor is None or not title:
        return
    title_key = (_normalize_text(title), _normalize_text(artist))
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
    monitor._netease_track_id = str(sample.get("track_id") or "")
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
            )
            monitor._evt_total_duration = sample.get("duration")
            monitor._evt_position = sample.get("position")
            monitor._evt_position_time = time.time()
            if getattr(monitor, "_current_timeline", None):
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
    if age > 2.0:
        return sample
    if playing and age > 0.05:
        sample["position"] = float(position) + min(age, 1.0)
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
    HzSoundBoxPixelMusicLyricModel.receive_data_from_usb = logged_receive
    _PROTOCOL_LOGGING_INSTALLED = True


class _CanvasBridge(QObject):
    request = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.request.connect(self.handle)

    @pyqtSlot(object)
    def handle(self, job):
        global _CANVAS_MODEL, _CANVAS_WALLPAPER_ID, _QQ_MODEL
        _log("canvas_handle_received", text=job.get("text", ""))
        try:
            from app.utils.hz_canvas_bin_utils import HzCanvasBinUtils

            _ensure_canvas_model()
            if _CANVAS_MODEL._is_ed03_running:
                if time.time() - _CANVAS_LAST_START > 8.0:
                    _CANVAS_MODEL._is_ed03_running = False
                    _log("canvas_stale_send_state_reset")
                else:
                    raise RuntimeError("画布正在传输上一帧，请稍后再试")

            matrix = _render_text_matrix(
                job.get("text", ""),
                job.get("font_family", _DEFAULT_SETTINGS["font_family"]),
                job.get("font_size", _DEFAULT_SETTINGS["font_size"]),
                job.get("font_weight", _DEFAULT_SETTINGS["font_weight"]),
            )
            spec = _CANVAS_MODEL.canvas_matrix_spec
            if _CANVAS_WALLPAPER_ID is None:
                file_bytes = HzCanvasBinUtils.matrix_to_bin(matrix, spec)
                _CANVAS_WALLPAPER_ID = HzCanvasBinUtils.get_wallpaper_id_from_bin(
                    file_bytes
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
                show=bool(job.get("show", False)),
                mode_group_index=getattr(_CANVAS_MODEL, "mode_group_index", None),
                wallpaper_count=len(
                    getattr(_CANVAS_MODEL, "wallpaper_combo_data", []) or []
                ),
            )
        except Exception as error:
            _log("canvas_error", error=str(error))


_CANVAS_BRIDGE = None


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
            result = super().receive_data_from_usb(report)
            if was_running and getattr(report, "index", None) == 257:
                # CM_ED01 is an unrelated settings query response.  The
                # original implementation clears the transfer flag here,
                # which can cancel an active canvas handshake.
                self._is_ed03_running = True
            return result

    _CANVAS_MODEL = _LoggedCanvasModel()
    _CANVAS_MODEL.set_device(qq_model.mdevice)
    _CANVAS_MODEL.query_pixel_setting()
    _log("canvas_model_initialized")
    return _CANVAS_MODEL


def _ensure_canvas_model_safe():
    try:
        _ensure_canvas_model()
    except Exception as error:
        _log("canvas_preinit_error", error=str(error))


def _ensure_native_lyrics_safe():
    try:
        if _load_settings().get("engine") == "native":
            _force_native_lyrics(
                _load_settings().get("lyrics_display_mode", 1)
            )
    except Exception as error:
        _log("native_lyrics_startup_error", error=str(error))


def _dispatch_canvas(job):
    _CANVAS_JOBS.put(job)
    _log("canvas_dispatch_queued", text=job.get("text", ""))


def _poll_canvas_jobs():
    latest = None
    while True:
        try:
            latest = _CANVAS_JOBS.get_nowait()
        except queue.Empty:
            break
    if latest is not None and _CANVAS_BRIDGE is not None:
        _CANVAS_BRIDGE.handle(latest)


class _LocalApiHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/settings":
            self._send(200, _load_settings())
            return
        if self.path == "/api/state":
            monitor = _ACTIVE_MONITOR
            progress = _netease_progress_snapshot(
                bool(getattr(monitor, "_evt_is_playing", None))
            )
            lyric_model = None
            try:
                lyric_model = _lyric_model_state(_get_lyric_model())
            except Exception as error:
                lyric_model = {"error": str(error)}
            self._send(
                200,
                {
                    "running": bool(monitor and getattr(monitor, "_running", False)),
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
                    "is_playing": (
                        getattr(monitor, "_evt_is_playing", None) if monitor else None
                    ),
                    "last_render": _LAST_RENDER,
                    "canvas_ready": _CANVAS_MODEL is not None,
                    "canvas_sending": bool(
                        getattr(_CANVAS_MODEL, "_is_ed03_running", False)
                    ),
                    "canvas_wallpaper_count": len(
                        getattr(_CANVAS_MODEL, "wallpaper_combo_data", []) or []
                    ),
                    "canvas_packet_index": getattr(
                        _CANVAS_MODEL, "_canvas_packet_index", None
                    ),
                },
            )
            return
        if self.path == "/api/diagnose":
            try:
                self._send(
                    200,
                    {
                        "lyric_model": _lyric_model_state(_get_lyric_model()),
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
        length = min(1024 * 1024, int(self.headers.get("Content-Length", "0")))
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._send(400, {"error": "invalid json"})
            return

        if self.path == "/api/settings":
            try:
                reapply_device = bool(payload.get("reapply_device", True))
                stored_payload = {
                    key: value
                    for key, value in payload.items()
                    if key != "reapply_device"
                }
                settings = _save_settings(stored_payload)
                monitor = _ACTIVE_MONITOR
                base_timeline = getattr(
                    monitor, "_netease_base_timeline", None
                ) if monitor else None
                if base_timeline:
                    offset_seconds = (
                        float(settings.get("line_offset_ms", 0) or 0) / 1000.0
                    )
                    monitor._current_timeline = [
                        (max(0.0, timestamp + offset_seconds), text)
                        for timestamp, text in base_timeline
                    ]
                    monitor._netease_timeline_times = [
                        float(timestamp)
                        for timestamp, _ in monitor._current_timeline
                    ]
                    monitor._netease_line_index = None
                    monitor._last_lyric_line = None
                    monitor._locate_and_send_lyric()
                result = {"settings": settings}
                if settings.get("engine") == "native" and reapply_device:
                    result["device"] = _force_native_lyrics(
                        settings.get("lyrics_display_mode", 1)
                    )
                    _save_settings({"engine": "native"})
                self._send(200, result)
            except Exception as error:
                self._send(500, {"error": str(error)})
            return
        if self.path == "/api/test-canvas":
            try:
                _dispatch_canvas(payload)
                self._send(202, {"status": "queued"})
            except Exception as error:
                self._send(500, {"error": str(error)})
            return
        if self.path == "/api/restore-native":
            try:
                settings = _save_settings({"engine": "native"})
                self._send(
                    200,
                    {
                        "status": "native",
                        "settings": settings,
                        "device": _force_native_lyrics(
                            settings.get("lyrics_display_mode", 1)
                        ),
                    },
                )
            except Exception as error:
                self._send(500, {"error": str(error)})
            return
        if self.path == "/api/diagnose":
            try:
                model = _get_lyric_model()
                model.query_pixel_setting()
                self._send(202, {"status": "query-sent"})
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
    global _ACTIVE_MONITOR, _CANVAS_TIMER, _QQ_MODEL
    _ACTIVE_MONITOR = self
    callback_owner = getattr(getattr(self, "_on_lyric_changed", None), "__self__", None)
    if callback_owner is not None:
        _QQ_MODEL = callback_owner
        _patch_qq_lyric_callback(callback_owner)
        self._on_lyric_changed = type(callback_owner)._on_lyric_text_changed.__get__(
            callback_owner, type(callback_owner)
        )
    if _CANVAS_TIMER is None:
        _CANVAS_TIMER = QTimer()
        _CANVAS_TIMER.setInterval(100)
        _CANVAS_TIMER.timeout.connect(_poll_canvas_jobs)
        _CANVAS_TIMER.start()
        _log("canvas_timer_started")
        QTimer.singleShot(2000, _ensure_canvas_model_safe)
        QTimer.singleShot(3000, _ensure_native_lyrics_safe)
        QTimer.singleShot(1200, _ensure_netease_running_safe)
    return _original_start(self)


def _patch_qq_lyric_callback(owner):
    model_class = type(owner)
    if getattr(model_class, "_netease_canvas_callback_patch", False):
        return
    original = model_class._on_lyric_text_changed

    def patched(self, lyric_line):
        settings = _load_settings()
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


def _fetch_and_parse_lyric_sync(self, title, artist, duration):
    if getattr(self, "_netease_source_active", False):
        try:
            track_id = str(getattr(self, "_netease_track_id", "") or "")
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
                timeline = parse_lrc_to_timeline(lyric)
                if timeline:
                    self._netease_base_timeline = list(timeline)
                    self._netease_line_index = None
                    self._netease_wait_until = time.time() + 0.55
                    offset_seconds = (
                        float(_load_settings().get("line_offset_ms", 0) or 0)
                        / 1000.0
                    )
                    if offset_seconds:
                        timeline = [
                            (max(0.0, timestamp + offset_seconds), text)
                            for timestamp, text in timeline
                        ]
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

_CANVAS_BRIDGE = _CanvasBridge()
_install_protocol_logging()
_start_netease_progress_bridge()
_start_local_api()
