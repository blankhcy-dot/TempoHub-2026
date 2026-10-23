from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
INTERNAL_DIR = APP_DIR / "_internal"
sys.path.insert(0, str(APP_DIR))
if INTERNAL_DIR.is_dir():
    local_qt_bin = APP_DIR / "PyQt6" / "Qt6" / "bin"
    if local_qt_bin.is_dir():
        os.add_dll_directory(str(local_qt_bin))
    os.add_dll_directory(str(INTERNAL_DIR))
    sys.path.append(str(INTERNAL_DIR))

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


API_BASE = "http://127.0.0.1:47653"
PREVIEW_WIDTH = 256
PREVIEW_HEIGHT = 32


def api_get(path: str, timeout: float = 3.0):
    with urllib.request.urlopen(API_BASE + path, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def api_post(path: str, payload: dict, timeout: float = 5.0):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        API_BASE + path,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def ensure_tempo_hub_running():
    try:
        api_get("/api/state", timeout=0.8)
        return True
    except Exception:
        pass

    executable = APP_DIR / "EDIFIER TempoHub.exe"
    if executable.is_file():
        try:
            subprocess.Popen(
                [str(executable)],
                cwd=str(APP_DIR),
                close_fds=True,
            )
        except Exception:
            return False

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        time.sleep(0.35)
        try:
            api_get("/api/state", timeout=0.8)
            return True
        except Exception:
            continue
    return False


def ensure_netease_running():
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:9222/json/list", timeout=0.8
        ):
            return True
    except Exception:
        pass

    try:
        result = api_post("/api/ensure-netease", {}, timeout=15.0)
        return bool(result.get("ready"))
    except Exception:
        pass

    existing = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq cloudmusic.exe", "/NH"],
        capture_output=True,
        text=True,
        check=False,
    )
    if "cloudmusic.exe" in existing.stdout.casefold():
        return False

    candidates = [
        Path(os.environ.get("ProgramFiles", "")) / "NetEase/CloudMusic/cloudmusic.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "NetEase/CloudMusic/cloudmusic.exe",
    ]
    executable = next((path for path in candidates if path.is_file()), None)
    if executable is None:
        return False
    try:
        subprocess.Popen(
            [str(executable), "--remote-debugging-port=9222"],
            cwd=str(executable.parent),
            close_fds=True,
        )
    except Exception:
        return False

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        time.sleep(0.4)
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:9222/json/list", timeout=0.8
            ):
                return True
        except Exception:
            continue
    return False


def format_seconds(value):
    if value is None:
        return "--:--"
    value = max(0, int(value))
    return f"{value // 60:02d}:{value % 60:02d}"


def format_metric(value):
    if value is None:
        return "--"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    return f"{number:.1f}".rstrip("0").rstrip(".")


def format_offset(milliseconds):
    value = int(milliseconds)
    if value == 0:
        return "0.00 s"
    return f"{value / 1000:+.2f} s"


class LyricPreview(QLabel):
    def __init__(self):
        super().__init__()
        self.setFixedSize(PREVIEW_WIDTH * 2, PREVIEW_HEIGHT * 2)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "background:#030405; border:1px solid #20262c; border-radius:12px;"
        )
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(34)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 140))
        self.setGraphicsEffect(shadow)
        self.render_text("HALO PIXELBAR")

    def render_text(self, text):
        image = QImage(
            PREVIEW_WIDTH,
            PREVIEW_HEIGHT,
            QImage.Format.Format_Grayscale8,
        )
        image.fill(QColor("#020304"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, False)
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(25)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        while (
            font.pixelSize() > 8
            and metrics.horizontalAdvance(text) > PREVIEW_WIDTH - 4
        ):
            font.setPixelSize(font.pixelSize() - 1)
            painter.setFont(font)
            metrics = QFontMetricsF(font)
        painter.setPen(QColor("white"))
        painter.drawText(
            QRectF(0, 0, PREVIEW_WIDTH, PREVIEW_HEIGHT),
            int(Qt.AlignmentFlag.AlignCenter.value),
            text,
        )
        painter.end()
        pixmap = QPixmap.fromImage(image).scaled(
            PREVIEW_WIDTH * 2,
            PREVIEW_HEIGHT * 2,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.setPixmap(pixmap)


class MatrixPreview(QLabel):
    def __init__(self):
        super().__init__()
        self.setFixedSize(PREVIEW_WIDTH * 2, PREVIEW_HEIGHT * 2)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "background:#030405; border:1px solid #20262c; border-radius:12px;"
        )
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(34)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 140))
        self.setGraphicsEffect(shadow)
        self.show_message("LIVE PREVIEW")

    def show_message(self, text):
        image = QImage(
            PREVIEW_WIDTH,
            PREVIEW_HEIGHT,
            QImage.Format.Format_Grayscale8,
        )
        image.fill(QColor("#020304"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, False)
        font = QFont("Consolas")
        font.setPixelSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("white"))
        painter.drawText(
            QRectF(0, 0, PREVIEW_WIDTH, PREVIEW_HEIGHT),
            int(Qt.AlignmentFlag.AlignCenter.value),
            text,
        )
        painter.end()
        self._set_image(image)

    def set_frame(self, encoded):
        try:
            packed = base64.b64decode(encoded or "")
        except Exception:
            return
        expected = PREVIEW_WIDTH * PREVIEW_HEIGHT // 8
        if len(packed) != expected:
            return
        image = QImage(
            PREVIEW_WIDTH,
            PREVIEW_HEIGHT,
            QImage.Format.Format_Grayscale8,
        )
        image.fill(QColor("black"))
        offset = 0
        for y in range(PREVIEW_HEIGHT):
            for x_byte in range(PREVIEW_WIDTH // 8):
                value = packed[offset]
                offset += 1
                for bit in range(8):
                    if value & (1 << (7 - bit)):
                        image.setPixelColor(x_byte * 8 + bit, y, QColor("white"))
        self._set_image(image)

    def _set_image(self, image):
        pixmap = QPixmap.fromImage(image).scaled(
            PREVIEW_WIDTH * 2,
            PREVIEW_HEIGHT * 2,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.setPixmap(pixmap)


class ToneCurvePreview(QLabel):
    def __init__(self):
        super().__init__()
        self.setFixedSize(520, 230)
        self.setStyleSheet(
            "background:#050809; border:1px solid #20262c; border-radius:12px;"
        )
        self.mode = 0
        self.render_curve()

    def set_mode(self, mode):
        self.mode = max(0, min(2, int(mode)))
        self.render_curve()

    def render_curve(self):
        image = QImage(520, 230, QImage.Format.Format_RGB32)
        image.fill(QColor("#050809"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        plot = QRectF(42, 28, 450, 148)
        painter.setPen(QPen(QColor("#293238"), 1))
        painter.drawRect(plot)
        painter.drawLine(
            int(plot.left()),
            int(plot.center().y()),
            int(plot.right()),
            int(plot.center().y()),
        )
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            x = plot.left() + plot.width() * fraction
            painter.drawLine(
                int(x),
                int(plot.top()),
                int(x),
                int(plot.bottom()),
            )
        curves = {
            0: [0.0, 0.8, 1.0, 0.9, 0.3, -0.2],
            1: [-0.8, -0.4, 0.3, 1.5, 1.2, 0.4],
            2: [2.3, 1.6, 0.2, 0.8, 1.3, 1.8],
        }
        colors = {
            0: QColor("#54e69a"),
            1: QColor("#58c8ff"),
            2: QColor("#ffb85c"),
        }
        values = curves[self.mode]
        path = QPainterPath()
        for index, value in enumerate(values):
            x = plot.left() + plot.width() * index / (len(values) - 1)
            y = plot.center().y() - value * 24
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.setPen(QPen(colors[self.mode], 3))
        painter.drawPath(path)
        labels = ("60", "250", "1k", "3k", "8k", "16k")
        painter.setFont(QFont("Consolas", 8))
        painter.setPen(QColor("#7f8a92"))
        for index, label in enumerate(labels):
            x = plot.left() + plot.width() * index / (len(labels) - 1)
            painter.drawText(QRectF(x - 24, plot.bottom() + 8, 48, 18), int(Qt.AlignmentFlag.AlignCenter.value), label)
        painter.drawText(
            QRectF(12, 5, 496, 18),
            int(Qt.AlignmentFlag.AlignLeft.value),
            "调音设计意图 · 非设备频响实测",
        )
        painter.end()
        self.setPixmap(QPixmap.fromImage(image))


class SettingsWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Halo PixelBar 控制台")
        self.setMinimumSize(1080, 660)
        self.resize(1180, 760)
        self.settings = {
            "enabled": True,
            "engine": "native",
            "line_offset_ms": 0,
            "scene": "lyrics",
            "audio_mode": "bars",
            "audio_sensitivity": 55,
            "notify_wechat": True,
            "notify_qq": True,
            "notify_qqmail": True,
            "perf_show_fps": True,
            "perf_show_cpu": True,
            "perf_show_gpu": True,
            "perf_show_memory": True,
            "sound_mode": 0,
        }
        self._suppress_offset_change = False
        self._suppress_scene_change = True
        self._build_ui()
        self.offset_apply_timer = QTimer(self)
        self.offset_apply_timer.setSingleShot(True)
        self.offset_apply_timer.setInterval(400)
        self.offset_apply_timer.timeout.connect(self._apply_offset)
        self.scene_apply_timer = QTimer(self)
        self.scene_apply_timer.setSingleShot(True)
        self.scene_apply_timer.setInterval(250)
        self.scene_apply_timer.timeout.connect(self._apply_scene_options)
        self._load_settings()
        self._suppress_scene_change = False
        self._refresh_state()
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._refresh_state)
        self.timer.start()
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(350)
        self.preview_timer.timeout.connect(self._refresh_scene_preview)
        self.preview_timer.start()

    def _card(self):
        card = QFrame()
        card.setObjectName("card")
        return card

    def _divider(self):
        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        return divider

    def _build_ui(self):
        self.setStyleSheet(
            """
            QMainWindow {
                background:#0B0E11;
            }
            QWidget {
                color:#F2F5F6;
                font-family:"Microsoft YaHei UI";
                font-size:13px;
            }
            QWidget#root { background:#0B0E11; }
            QLabel { background:transparent; }
            QFrame#card {
                background:#12161A;
                border:1px solid #242B32;
                border-radius:20px;
            }
            QFrame#divider { background:#242B32; border:0; }
            QLabel#eyebrow {
                color:#6F7B84;
                font-size:10px;
                font-weight:700;
            }
            QLabel#brand {
                color:#FFFFFF;
                font-size:20px;
                font-weight:700;
            }
            QLabel#subtitle { color:#7C8790; font-size:12px; }
            QLabel#section {
                color:#DDE3E7;
                font-size:14px;
                font-weight:700;
            }
            QLabel#songTitle {
                color:#FFFFFF;
                font-size:25px;
                font-weight:700;
            }
            QLabel#artist { color:#84909A; font-size:13px; }
            QLabel#lyric {
                color:#E8EDF0;
                font-size:18px;
                font-weight:600;
            }
            QLabel#muted { color:#68747D; font-size:11px; }
            QLabel#offsetValue {
                background:#18221D;
                color:#5EE59B;
                border:1px solid #284735;
                border-radius:12px;
                padding:6px 11px;
                font-size:14px;
                font-weight:700;
            }
            QLabel#chipGood {
                background:#12251A;
                color:#63E89D;
                border:1px solid #254A34;
                border-radius:11px;
                padding:5px 10px;
                font-size:11px;
                font-weight:600;
            }
            QLabel#chipMuted {
                background:#181D21;
                color:#8A959E;
                border:1px solid #2B333A;
                border-radius:11px;
                padding:5px 10px;
                font-size:11px;
            }
            QLabel#chipWarn {
                background:#2A2113;
                color:#FFCE76;
                border:1px solid #574321;
                border-radius:11px;
                padding:5px 10px;
                font-size:11px;
            }
            QLabel#connection {
                background:#141B18;
                color:#73E9A5;
                border:1px solid #253F31;
                border-radius:14px;
                padding:7px 13px;
            }
            QProgressBar {
                background:#222A30;
                border:0;
                border-radius:3px;
                min-height:6px;
                max-height:6px;
            }
            QProgressBar::chunk {
                background:#46DB8C;
                border-radius:3px;
            }
            QSlider#offsetSlider::groove:horizontal {
                height:6px;
                background:#252D34;
                border-radius:3px;
            }
            QSlider#offsetSlider::sub-page:horizontal {
                background:#3BD887;
                border-radius:3px;
            }
            QSlider#offsetSlider::handle:horizontal {
                width:20px;
                height:20px;
                margin:-7px 0;
                border:3px solid #0B0E11;
                border-radius:10px;
                background:#F5FAF7;
            }
            QPushButton {
                background:#1B2126;
                color:#DDE3E7;
                border:1px solid #303941;
                border-radius:11px;
                padding:9px 15px;
                font-weight:600;
            }
            QPushButton:hover { background:#222A30; border-color:#3B4650; }
            QPushButton#primary {
                background:#42DE8C;
                color:#04110A;
                border:0;
                padding:10px 20px;
            }
            QPushButton#primary:hover { background:#56ECA0; }
            QPushButton:checked {
                background:#16271E;
                color:#62E79E;
                border:1px solid #28513A;
            }
            QPushButton#quiet {
                background:transparent;
                border:0;
                color:#7E8A93;
                padding:5px 8px;
            }
            QPushButton#quiet:hover { color:#E8EDF0; }
            QFrame#navCard {
                background:#101418;
                border:1px solid #242B32;
                border-radius:20px;
            }
            QLabel#navTitle {
                color:#FFFFFF;
                font-size:16px;
                font-weight:700;
            }
            QListWidget#sceneNav {
                background:transparent;
                border:0;
                outline:0;
            }
            QListWidget#sceneNav::item {
                color:#8C979F;
                border-radius:12px;
                padding:12px 12px;
                margin:3px 0;
            }
            QListWidget#sceneNav::item:hover {
                background:#171D22;
                color:#F0F4F6;
            }
            QListWidget#sceneNav::item:selected {
                background:#16271E;
                color:#62E79E;
                border:1px solid #28513A;
            }
            QComboBox {
                background:#171C21;
                color:#E9EEF1;
                border:1px solid #303941;
                border-radius:10px;
                padding:7px 10px;
            }
            QComboBox::drop-down { border:0; width:24px; }
            QCheckBox {
                color:#C9D1D6;
                spacing:9px;
                padding:5px 0;
            }
            QCheckBox::indicator {
                width:16px;
                height:16px;
                border-radius:5px;
                border:1px solid #3A454E;
                background:#171C21;
            }
            QCheckBox::indicator:checked {
                background:#42DE8C;
                border-color:#42DE8C;
            }
            """
        )

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 22, 24, 22)
        outer.setSpacing(16)

        header = QHBoxLayout()
        brand_box = QVBoxLayout()
        brand_box.setSpacing(3)
        brand = QLabel("Halo PixelBar")
        brand.setObjectName("brand")
        subtitle = QLabel("Halo PixelBar 控制台  ·  歌词 / 频谱 / 通知 / 性能")
        subtitle.setObjectName("subtitle")
        brand_box.addWidget(brand)
        brand_box.addWidget(subtitle)
        header.addLayout(brand_box)
        header.addStretch()
        self.status = QLabel("正在连接 TempoHub…")
        self.status.setObjectName("connection")
        header.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(16)
        outer.addLayout(body, 1)

        nav_card = QFrame()
        nav_card.setObjectName("navCard")
        nav_card.setFixedWidth(190)
        nav_layout = QVBoxLayout(nav_card)
        nav_layout.setContentsMargins(16, 20, 16, 18)
        nav_layout.setSpacing(12)
        nav_title = QLabel("显示场景")
        nav_title.setObjectName("navTitle")
        nav_layout.addWidget(nav_title)
        nav_hint = QLabel("选择要投送到 Halo PixelBar 的应用")
        nav_hint.setObjectName("muted")
        nav_hint.setWordWrap(True)
        nav_layout.addWidget(nav_hint)
        self.nav = QListWidget()
        self.nav.setObjectName("sceneNav")
        for text in ("歌词", "音频频谱", "消息通知", "游戏性能", "音效调优"):
            self.nav.addItem(text)
        self.nav.setCurrentRow(0)
        nav_layout.addWidget(self.nav, 1)
        self.nav_state = QLabel("设备画面随场景自动切换")
        self.nav_state.setObjectName("muted")
        self.nav_state.setWordWrap(True)
        nav_layout.addWidget(self.nav_state)
        body.addWidget(nav_card)

        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        self.lyrics_page = QWidget()
        lyrics_page_layout = QHBoxLayout(self.lyrics_page)
        lyrics_page_layout.setContentsMargins(0, 0, 0, 0)
        lyrics_page_layout.setSpacing(16)
        self.pages.addWidget(self.lyrics_page)

        preview_card = self._card()
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(26, 22, 26, 22)
        preview_layout.setSpacing(12)

        eyebrow = QLabel("NOW PLAYING")
        eyebrow.setObjectName("eyebrow")
        preview_layout.addWidget(eyebrow)
        self.preview = LyricPreview()
        preview_layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)

        self.song_label = QLabel("等待播放音乐…")
        self.song_label.setObjectName("songTitle")
        self.song_label.setWordWrap(True)
        preview_layout.addWidget(self.song_label)
        self.artist_label = QLabel("在网易云播放歌曲后会自动获取歌词")
        self.artist_label.setObjectName("artist")
        self.artist_label.setWordWrap(True)
        preview_layout.addWidget(self.artist_label)
        preview_layout.addWidget(self._divider())

        lyric_eyebrow = QLabel("CURRENT LYRIC")
        lyric_eyebrow.setObjectName("eyebrow")
        preview_layout.addWidget(lyric_eyebrow)
        self.lyric_label = QLabel("等待歌词…")
        self.lyric_label.setObjectName("lyric")
        self.lyric_label.setWordWrap(True)
        self.lyric_label.setMinimumHeight(48)
        preview_layout.addWidget(self.lyric_label)
        preview_layout.addStretch()

        progress_head = QHBoxLayout()
        self.current_time = QLabel("--:--")
        self.current_time.setObjectName("muted")
        self.duration_time = QLabel("--:--")
        self.duration_time.setObjectName("muted")
        progress_head.addWidget(self.current_time)
        progress_head.addStretch()
        progress_head.addWidget(self.duration_time)
        preview_layout.addLayout(progress_head)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        preview_layout.addWidget(self.progress)

        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        self.device_chip = QLabel("正在检查设备…")
        self.device_chip.setObjectName("chipMuted")
        self.sync_chip = QLabel("等待播放进度")
        self.sync_chip.setObjectName("chipMuted")
        chip_row.addWidget(self.device_chip)
        chip_row.addWidget(self.sync_chip)
        chip_row.addStretch()
        preview_layout.addLayout(chip_row)
        lyrics_page_layout.addWidget(preview_card, 3)

        settings_card = self._card()
        settings_layout = QVBoxLayout(settings_card)
        settings_layout.setContentsMargins(24, 22, 24, 20)
        settings_layout.setSpacing(12)

        settings_eyebrow = QLabel("SYNC CONTROL")
        settings_eyebrow.setObjectName("eyebrow")
        settings_layout.addWidget(settings_eyebrow)
        settings_title = QLabel("歌词偏移")
        settings_title.setObjectName("section")
        settings_layout.addWidget(settings_title)
        settings_hint = QLabel(
            "拖动横轴微调歌词时间。向正值移动会让歌词提前，向负值移动会延后。"
        )
        settings_hint.setObjectName("muted")
        settings_hint.setWordWrap(True)
        settings_layout.addWidget(settings_hint)

        offset_head = QHBoxLayout()
        self.offset_value = QLabel("0.00 s")
        self.offset_value.setObjectName("offsetValue")
        self.reset_offset_btn = QPushButton("归零")
        self.reset_offset_btn.setObjectName("quiet")
        offset_head.addWidget(self.offset_value)
        offset_head.addStretch()
        offset_head.addWidget(self.reset_offset_btn)
        settings_layout.addLayout(offset_head)

        self.offset = QSlider(Qt.Orientation.Horizontal)
        self.offset.setObjectName("offsetSlider")
        self.offset.setRange(-5000, 5000)
        self.offset.setSingleStep(50)
        self.offset.setPageStep(500)
        self.offset.setTickInterval(1000)
        self.offset.setTickPosition(QSlider.TickPosition.NoTicks)
        settings_layout.addWidget(self.offset)

        scale_row = QHBoxLayout()
        for text in ("-5 s", "0", "+5 s"):
            label = QLabel(text)
            label.setObjectName("muted")
            scale_row.addWidget(label)
            if text != "+5 s":
                scale_row.addStretch()
        settings_layout.addLayout(scale_row)
        settings_layout.addWidget(self._divider())

        device_title = QLabel("设备显示")
        device_title.setObjectName("section")
        settings_layout.addWidget(device_title)
        device_hint = QLabel(
            "使用 Halo PixelBar 原生歌词模式，保留设备内置字体和歌词动画。"
        )
        device_hint.setObjectName("muted")
        device_hint.setWordWrap(True)
        settings_layout.addWidget(device_hint)

        self.device_state = QLabel("正在读取设备状态…")
        self.device_state.setObjectName("chipMuted")
        settings_layout.addWidget(
            self.device_state, 0, Qt.AlignmentFlag.AlignLeft
        )
        settings_layout.addStretch()

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.restore_btn = QPushButton("重新开启歌词")
        self.apply_btn = QPushButton("应用设置")
        self.apply_btn.setObjectName("primary")
        actions.addWidget(self.restore_btn)
        actions.addStretch()
        actions.addWidget(self.apply_btn)
        settings_layout.addLayout(actions)
        lyrics_page_layout.addWidget(settings_card, 2)

        self.audio_page, self.audio_preview = self._build_audio_page()
        self.notification_page, self.notification_preview = (
            self._build_notification_page()
        )
        self.performance_page, self.performance_preview = (
            self._build_performance_page()
        )
        self.sound_page = self._build_sound_page()
        self.pages.addWidget(self.audio_page)
        self.pages.addWidget(self.notification_page)
        self.pages.addWidget(self.performance_page)
        self.pages.addWidget(self.sound_page)

        self.offset.valueChanged.connect(self._on_offset_changed)
        self.offset.sliderReleased.connect(self._apply_offset)
        self.reset_offset_btn.clicked.connect(lambda: self.offset.setValue(0))
        self.apply_btn.clicked.connect(self._apply)
        self.restore_btn.clicked.connect(self._restore_native)
        self.nav.currentRowChanged.connect(self._switch_scene)

    def _build_audio_page(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        preview_card = self._card()
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(26, 22, 26, 22)
        preview_layout.setSpacing(12)
        eyebrow = QLabel("SYSTEM AUDIO")
        eyebrow.setObjectName("eyebrow")
        preview_layout.addWidget(eyebrow)
        title = QLabel("实时音频频谱")
        title.setObjectName("songTitle")
        preview_layout.addWidget(title)
        hint = QLabel("采集 Windows 系统输出，网易云、QQ 音乐和浏览器声音均可使用。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        preview_layout.addWidget(hint)
        preview = MatrixPreview()
        preview_layout.addWidget(preview, 0, Qt.AlignmentFlag.AlignHCenter)
        preview_layout.addWidget(self._divider())
        self.audio_metrics = QLabel("等待系统音频")
        self.audio_metrics.setObjectName("lyric")
        preview_layout.addWidget(self.audio_metrics)
        preview_layout.addStretch()
        self.audio_status = QLabel("系统音频监听准备中")
        self.audio_status.setObjectName("chipMuted")
        preview_layout.addWidget(
            self.audio_status, 0, Qt.AlignmentFlag.AlignLeft
        )
        layout.addWidget(preview_card, 3)

        controls = self._card()
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(24, 22, 24, 20)
        controls_layout.setSpacing(12)
        control_eyebrow = QLabel("VISUALIZER")
        control_eyebrow.setObjectName("eyebrow")
        controls_layout.addWidget(control_eyebrow)
        control_title = QLabel("显示样式")
        control_title.setObjectName("section")
        controls_layout.addWidget(control_title)

        mode_label = QLabel("频谱模式")
        mode_label.setObjectName("muted")
        controls_layout.addWidget(mode_label)
        self.audio_mode = QComboBox()
        self.audio_mode.addItem("柱状频谱", "bars")
        self.audio_mode.addItem("波形", "wave")
        self.audio_mode.addItem("双 VU 表", "vu")
        controls_layout.addWidget(self.audio_mode)

        sensitivity_title = QLabel("灵敏度")
        sensitivity_title.setObjectName("section")
        controls_layout.addWidget(sensitivity_title)
        self.audio_sensitivity_value = QLabel("55")
        self.audio_sensitivity_value.setObjectName("offsetValue")
        controls_layout.addWidget(
            self.audio_sensitivity_value, 0, Qt.AlignmentFlag.AlignLeft
        )
        self.audio_sensitivity = QSlider(Qt.Orientation.Horizontal)
        self.audio_sensitivity.setObjectName("offsetSlider")
        self.audio_sensitivity.setRange(20, 100)
        self.audio_sensitivity.setSingleStep(5)
        controls_layout.addWidget(self.audio_sensitivity)
        sensitivity_hint = QLabel(
            "灵敏度越高，低音量时柱形变化越明显。系统音频通过 WASAPI loopback 采集。"
        )
        sensitivity_hint.setObjectName("muted")
        sensitivity_hint.setWordWrap(True)
        controls_layout.addWidget(sensitivity_hint)
        controls_layout.addStretch()
        audio_apply = QPushButton("应用频谱设置")
        audio_apply.setObjectName("primary")
        audio_apply.clicked.connect(self._apply_scene_options)
        controls_layout.addWidget(audio_apply)
        layout.addWidget(controls, 2)

        self.audio_mode.currentIndexChanged.connect(self._schedule_scene_apply)
        self.audio_sensitivity.valueChanged.connect(self._on_audio_sensitivity)
        return page, preview

    def _build_notification_page(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        preview_card = self._card()
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(26, 22, 26, 22)
        preview_layout.setSpacing(12)
        eyebrow = QLabel("MESSAGE ALERTS")
        eyebrow.setObjectName("eyebrow")
        preview_layout.addWidget(eyebrow)
        title = QLabel("微信、QQ 与邮箱通知")
        title.setObjectName("songTitle")
        preview_layout.addWidget(title)
        hint = QLabel("检测到未读消息时，在屏幕顶部显示发送应用和消息摘要。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        preview_layout.addWidget(hint)
        preview = MatrixPreview()
        preview_layout.addWidget(preview, 0, Qt.AlignmentFlag.AlignHCenter)
        preview_layout.addWidget(self._divider())
        self.notification_latest = QLabel("暂无新通知")
        self.notification_latest.setObjectName("lyric")
        self.notification_latest.setWordWrap(True)
        preview_layout.addWidget(self.notification_latest)
        preview_layout.addStretch()
        self.notification_status = QLabel("正在连接 Windows 通知")
        self.notification_status.setObjectName("chipMuted")
        preview_layout.addWidget(
            self.notification_status, 0, Qt.AlignmentFlag.AlignLeft
        )
        layout.addWidget(preview_card, 3)

        controls = self._card()
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(24, 22, 24, 20)
        controls_layout.setSpacing(12)
        control_eyebrow = QLabel("MONITOR")
        control_eyebrow.setObjectName("eyebrow")
        controls_layout.addWidget(control_eyebrow)
        control_title = QLabel("监听范围")
        control_title.setObjectName("section")
        controls_layout.addWidget(control_title)
        self.notify_wechat = QCheckBox("微信")
        self.notify_qq = QCheckBox("QQ")
        self.notify_qqmail = QCheckBox("QQ 邮箱")
        controls_layout.addWidget(self.notify_wechat)
        controls_layout.addWidget(self.notify_qq)
        controls_layout.addWidget(self.notify_qqmail)
        notification_hint = QLabel(
            "优先读取 Windows 通知中心；权限不可用时回退到未读窗口标题检测。"
        )
        notification_hint.setObjectName("muted")
        notification_hint.setWordWrap(True)
        controls_layout.addWidget(notification_hint)
        controls_layout.addStretch()
        wechat_test = QPushButton("测试微信通知")
        qq_test = QPushButton("测试 QQ 通知")
        mail_test = QPushButton("测试 QQ 邮箱")
        wechat_test.clicked.connect(
            lambda: self._test_notification("微信", "你有一条新的微信消息")
        )
        qq_test.clicked.connect(
            lambda: self._test_notification("QQ", "你收到了一条新的 QQ 消息")
        )
        mail_test.clicked.connect(
            lambda: self._test_notification("QQ邮箱", "你收到了一封新邮件")
        )
        controls_layout.addWidget(wechat_test)
        controls_layout.addWidget(qq_test)
        controls_layout.addWidget(mail_test)
        layout.addWidget(controls, 2)

        for checkbox in (self.notify_wechat, self.notify_qq, self.notify_qqmail):
            checkbox.checkStateChanged.connect(self._schedule_scene_apply)
        return page, preview

    def _build_performance_page(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        preview_card = self._card()
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(26, 22, 26, 22)
        preview_layout.setSpacing(12)
        eyebrow = QLabel("GAME TELEMETRY")
        eyebrow.setObjectName("eyebrow")
        preview_layout.addWidget(eyebrow)
        title = QLabel("游戏性能曲线")
        title.setObjectName("songTitle")
        preview_layout.addWidget(title)
        hint = QLabel("四路曲线依次显示 FPS、CPU、GPU 和内存；GPU 同时显示温度。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        preview_layout.addWidget(hint)
        preview = MatrixPreview()
        preview_layout.addWidget(preview, 0, Qt.AlignmentFlag.AlignHCenter)
        preview_layout.addWidget(self._divider())
        self.performance_values = QLabel("等待性能数据")
        self.performance_values.setObjectName("lyric")
        self.performance_values.setWordWrap(True)
        preview_layout.addWidget(self.performance_values)
        preview_layout.addStretch()
        self.performance_status = QLabel("CPU / GPU / 内存采样运行中")
        self.performance_status.setObjectName("chipMuted")
        preview_layout.addWidget(
            self.performance_status, 0, Qt.AlignmentFlag.AlignLeft
        )
        layout.addWidget(preview_card, 3)

        controls = self._card()
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(24, 22, 24, 20)
        controls_layout.setSpacing(12)
        control_eyebrow = QLabel("FRAME RATE")
        control_eyebrow.setObjectName("eyebrow")
        controls_layout.addWidget(control_eyebrow)
        control_title = QLabel("FPS 采集")
        control_title.setObjectName("section")
        controls_layout.addWidget(control_title)
        fps_hint = QLabel(
            "FPS 由 Intel PresentMon 采集，首次启用会弹出一次 Windows 管理员授权。"
        )
        fps_hint.setObjectName("muted")
        fps_hint.setWordWrap(True)
        controls_layout.addWidget(fps_hint)
        self.fps_button = QPushButton("启用 FPS 采集")
        self.fps_button.setObjectName("primary")
        self.fps_button.clicked.connect(self._start_fps_capture)
        controls_layout.addWidget(self.fps_button)
        self.fps_status = QLabel("FPS 尚未启用")
        self.fps_status.setObjectName("chipMuted")
        controls_layout.addWidget(self.fps_status)
        controls_layout.addWidget(self._divider())
        detail = QLabel(
            "CPU 和内存约每秒采样；NVIDIA GPU 使用 nvidia-smi。"
            "CPU 温度在当前驱动不允许普通权限访问时会显示为 --。"
        )
        detail.setObjectName("muted")
        detail.setWordWrap(True)
        controls_layout.addWidget(detail)
        controls_layout.addStretch()
        layout.addWidget(controls, 2)
        return page, preview

    def _build_sound_page(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        preview_card = self._card()
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(26, 22, 26, 22)
        preview_layout.setSpacing(12)
        eyebrow = QLabel("HARDWARE SOUND")
        eyebrow.setObjectName("eyebrow")
        preview_layout.addWidget(eyebrow)
        title = QLabel("音效调优")
        title.setObjectName("songTitle")
        preview_layout.addWidget(title)
        hint = QLabel(
            "直接切换 Halo PixelBar 的硬件 DSP 预设。曲线仅用于解释调音方向，不代表实测频响。"
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        preview_layout.addWidget(hint)
        self.sound_curve = ToneCurvePreview()
        preview_layout.addWidget(self.sound_curve)
        preview_layout.addWidget(self._divider())
        self.sound_mode_title = QLabel("音乐模式")
        self.sound_mode_title.setObjectName("lyric")
        preview_layout.addWidget(self.sound_mode_title)
        self.sound_mode_detail = QLabel(
            "相对均衡，人声和乐器兼顾，适合流行、女声、播客和长时间聆听。"
        )
        self.sound_mode_detail.setObjectName("muted")
        self.sound_mode_detail.setWordWrap(True)
        preview_layout.addWidget(self.sound_mode_detail)
        preview_layout.addStretch()
        self.sound_capability = QLabel("正在读取设备 EQ 能力…")
        self.sound_capability.setObjectName("chipMuted")
        preview_layout.addWidget(
            self.sound_capability, 0, Qt.AlignmentFlag.AlignLeft
        )
        layout.addWidget(preview_card, 3)

        controls = self._card()
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(24, 22, 24, 20)
        controls_layout.setSpacing(10)
        control_eyebrow = QLabel("LISTENING MODE")
        control_eyebrow.setObjectName("eyebrow")
        controls_layout.addWidget(control_eyebrow)
        control_title = QLabel("选择硬件模式")
        control_title.setObjectName("section")
        controls_layout.addWidget(control_title)

        self.sound_group = QButtonGroup(self)
        self.sound_group.setExclusive(True)
        self.sound_buttons = []
        texts = (
            "音乐  ·  均衡自然\n人声 / 流行 / 长时间聆听",
            "游戏  ·  定位清晰\n脚步、方向感与中高频细节",
            "电影  ·  氛围增强\n对白存在感与低频冲击",
        )
        for index, text in enumerate(texts):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setMinimumHeight(62)
            button.clicked.connect(
                lambda _checked=False, selected=index: self._set_sound_mode(selected)
            )
            self.sound_group.addButton(button, index)
            self.sound_buttons.append(button)
            controls_layout.addWidget(button)

        controls_layout.addWidget(self._divider())
        guidance = QLabel(
            "实用建议\n"
            "· 人声发闷：优先音乐模式，音量控制在 16–24。\n"
            "· 电影对白不清：电影模式，但夜间不要盲目提高音量。\n"
            "· FPS 游戏：游戏模式，减少持续低频带来的听觉疲劳。\n"
            "· 桌面近距离使用：不要把音量长期推到最大。"
        )
        guidance.setObjectName("muted")
        guidance.setWordWrap(True)
        controls_layout.addWidget(guidance)
        controls_layout.addStretch()
        self.sound_status = QLabel("等待选择模式")
        self.sound_status.setObjectName("chipMuted")
        controls_layout.addWidget(self.sound_status)
        layout.addWidget(controls, 2)
        return page

    def _load_eq_capability(self):
        try:
            info = api_get("/api/eq/info", timeout=4.0)
            eq_index = info.get("eq_index")
            probe = info.get("custom_eq_probe") or {}
            custom_supported = bool(probe.get("supported"))
            text = f"硬件 EQ 类型 {eq_index} · 3 个预设"
            text += " · 支持自定义 EQ" if custom_supported else " · 不支持自定义频段"
            self._set_chip(
                self.sound_capability,
                text,
                "good" if custom_supported else "muted",
            )
        except Exception as error:
            self._set_chip(
                self.sound_capability,
                f"设备 EQ 状态读取失败：{error}",
                "warn",
            )

    def _set_sound_mode(self, index):
        modes = (
            (
                "音乐模式",
                "相对均衡，人声和乐器兼顾，适合流行、女声、播客和长时间聆听。",
            ),
            (
                "游戏模式",
                "加强脚步、方向和环境中高频细节，同时控制持续低频，适合 FPS、MOBA 和竞速。",
            ),
            (
                "电影模式",
                "强调对白存在感和低频氛围，动态更积极；长时间音乐聆听可能不如音乐模式自然。",
            ),
        )
        try:
            api_post("/api/eq/preset", {"index": index}, timeout=5.0)
            api_post(
                "/api/settings",
                {"sound_mode": index, "reapply_device": False},
                timeout=4.0,
            )
            self.settings["sound_mode"] = index
            if 0 <= index < len(self.sound_buttons):
                self.sound_buttons[index].setChecked(True)
            self.sound_curve.set_mode(index)
            self.sound_mode_title.setText(modes[index][0])
            self.sound_mode_detail.setText(modes[index][1])
            self._set_chip(self.sound_status, "硬件模式已切换", "good")
        except Exception as error:
            self._set_chip(self.sound_status, f"切换失败：{error}", "warn")

    def _selected_scene(self):
        if self.nav.currentRow() >= 4:
            return self.settings.get("scene", "lyrics")
        return ("lyrics", "audio", "notifications", "performance")[
            max(0, min(3, self.nav.currentRow()))
        ]

    def _schedule_scene_apply(self):
        if not self._suppress_scene_change:
            self.scene_apply_timer.start()

    def _switch_scene(self, row):
        self.pages.setCurrentIndex(row)
        names = ("歌词", "音频频谱", "消息通知", "游戏性能", "音效调优")
        self.nav_state.setText(f"当前显示：{names[row]}")
        if row == 4:
            self._load_eq_capability()
        elif not self._suppress_scene_change:
            self._apply_scene_options()

    def _apply_scene_options(self):
        self.scene_apply_timer.stop()
        try:
            result = api_post(
                "/api/settings",
                self._settings_payload(
                    reapply_device=self._selected_scene() == "lyrics"
                ),
                timeout=12.0,
            )
            self.settings.update(result.get("settings", {}))
            self.nav_state.setText(
                f"当前显示：{('歌词', '音频频谱', '消息通知', '游戏性能', '音效调优')[self.nav.currentRow()]}"
            )
        except Exception as error:
            self.nav_state.setText(f"场景切换失败：{error}")

    def _on_audio_sensitivity(self, value):
        self.audio_sensitivity_value.setText(str(int(value)))
        self._schedule_scene_apply()

    def _test_notification(self, app_name, text):
        try:
            api_post(
                "/api/notifications/test",
                {"app": app_name, "text": text},
                timeout=3.0,
            )
            self.notification_latest.setText(f"{app_name} · {text}")
            self._set_chip(self.notification_status, "测试通知已发送", "good")
        except Exception as error:
            self._set_chip(self.notification_status, f"测试失败：{error}", "warn")

    def _start_fps_capture(self):
        self.fps_button.setEnabled(False)
        self._set_chip(self.fps_status, "等待管理员授权…", "muted")
        try:
            result = api_post(
                "/api/performance/start-fps",
                {},
                timeout=60.0,
            )
            status = result.get("status") or "启动中"
            error = result.get("error")
            self._set_chip(
                self.fps_status,
                error or status,
                "warn" if error else "good",
            )
        except Exception as error:
            self._set_chip(self.fps_status, f"启动失败：{error}", "warn")
        finally:
            self.fps_button.setEnabled(True)

    def _refresh_scene_preview(self):
        if self.nav.currentRow() in (0, 4):
            return
        try:
            frame = api_get("/api/scene-frame", timeout=1.5)
            self.pages.currentWidget().findChild(MatrixPreview).set_frame(
                frame.get("matrix", "")
            )
        except Exception:
            pass

    def _settings_payload(self, reapply_device=False):
        scene = self._selected_scene()
        return {
            "enabled": True,
            "scene": scene,
            "engine": "native" if scene == "lyrics" else "custom",
            "line_offset_ms": self.offset.value(),
            "audio_mode": self.audio_mode.currentData(),
            "audio_sensitivity": self.audio_sensitivity.value(),
            "notify_wechat": self.notify_wechat.isChecked(),
            "notify_qq": self.notify_qq.isChecked(),
            "notify_qqmail": self.notify_qqmail.isChecked(),
            "sound_mode": self.sound_group.checkedId(),
            "reapply_device": bool(reapply_device),
        }

    def _set_offset(self, milliseconds):
        self._suppress_offset_change = True
        self.offset.setValue(int(milliseconds))
        self.offset_value.setText(format_offset(milliseconds))
        self._suppress_offset_change = False

    def _load_settings(self):
        try:
            self.settings.update(api_get("/api/settings"))
        except Exception:
            pass
        self._set_offset(int(self.settings.get("line_offset_ms", 0)))
        sound_mode = max(
            0,
            min(2, int(self.settings.get("sound_mode", 0))),
        )
        if hasattr(self, "sound_buttons"):
            self.sound_buttons[sound_mode].setChecked(True)
            self.sound_curve.set_mode(sound_mode)
            self._set_sound_mode_label(sound_mode)
        scene_index = {
            "lyrics": 0,
            "audio": 1,
            "notifications": 2,
            "performance": 3,
        }.get(self.settings.get("scene", "lyrics"), 0)
        self.nav.setCurrentRow(scene_index)
        self.pages.setCurrentIndex(scene_index)
        audio_index = self.audio_mode.findData(
            self.settings.get("audio_mode", "bars")
        )
        self.audio_mode.setCurrentIndex(max(0, audio_index))
        self.audio_sensitivity.setValue(
            int(self.settings.get("audio_sensitivity", 55))
        )
        self.audio_sensitivity_value.setText(
            str(self.audio_sensitivity.value())
        )
        self.notify_wechat.setChecked(
            bool(self.settings.get("notify_wechat", True))
        )
        self.notify_qq.setChecked(bool(self.settings.get("notify_qq", True)))
        self.notify_qqmail.setChecked(
            bool(self.settings.get("notify_qqmail", True))
        )

    def _set_sound_mode_label(self, index):
        details = (
            (
                "音乐模式",
                "相对均衡，人声和乐器兼顾，适合流行、女声、播客和长时间聆听。",
            ),
            (
                "游戏模式",
                "加强脚步、方向和环境中高频细节，同时控制持续低频，适合 FPS、MOBA 和竞速。",
            ),
            (
                "电影模式",
                "强调对白存在感和低频氛围，动态更积极；长时间音乐聆听可能不如音乐模式自然。",
            ),
        )
        title, detail = details[max(0, min(2, int(index)))]
        self.sound_mode_title.setText(title)
        self.sound_mode_detail.setText(detail)

    def _on_offset_changed(self, value):
        self.offset_value.setText(format_offset(value))
        if not self._suppress_offset_change:
            self.offset_apply_timer.start()

    def _apply_offset(self):
        self.offset_apply_timer.stop()
        try:
            result = api_post(
                "/api/settings", self._settings_payload(reapply_device=False)
            )
            self.settings.update(result.get("settings", {}))
            self.sync_chip.setText(f"偏移 {format_offset(self.offset.value())}")
            self.sync_chip.setObjectName("chipGood")
            self.sync_chip.style().unpolish(self.sync_chip)
            self.sync_chip.style().polish(self.sync_chip)
        except Exception as error:
            self.sync_chip.setText("偏移保存失败")
            self.sync_chip.setObjectName("chipWarn")
            self.sync_chip.setToolTip(str(error))
            self.sync_chip.style().unpolish(self.sync_chip)
            self.sync_chip.style().polish(self.sync_chip)

    def _apply(self):
        self.offset_apply_timer.stop()
        try:
            result = api_post(
                "/api/settings", self._settings_payload(reapply_device=True)
            )
            self.settings.update(result.get("settings", {}))
            self.status.setText("已连接 TempoHub")
            self.device_state.setText(
                "歌词模式已重新应用"
                if self._selected_scene() == "lyrics"
                else "显示场景已应用"
            )
            self.device_state.setObjectName("chipGood")
            self.device_state.style().unpolish(self.device_state)
            self.device_state.style().polish(self.device_state)
        except Exception as error:
            self.status.setText(f"应用失败：{error}")
            self.status.setStyleSheet(
                "background:#2A2113; color:#FFCE76; padding:7px 13px;"
                "border:1px solid #574321; border-radius:14px;"
            )

    def _restore_native(self):
        try:
            api_post("/api/restore-native", {})
            self._suppress_scene_change = True
            self.nav.setCurrentRow(0)
            self._suppress_scene_change = False
            self.device_state.setText("已重新开启设备歌词")
            self.device_state.setObjectName("chipGood")
            self.device_state.style().unpolish(self.device_state)
            self.device_state.style().polish(self.device_state)
        except Exception as error:
            self.device_state.setText(f"操作失败：{error}")
            self.device_state.setObjectName("chipWarn")
            self.device_state.style().unpolish(self.device_state)
            self.device_state.style().polish(self.device_state)

    def _set_chip(self, label, text, state):
        names = {
            "good": "chipGood",
            "muted": "chipMuted",
            "warn": "chipWarn",
        }
        label.setText(text)
        label.setObjectName(names[state])
        label.style().unpolish(label)
        label.style().polish(label)

    def _refresh_state(self):
        try:
            state = api_get("/api/state")
        except Exception:
            self.status.setText("TempoHub 未运行")
            self.status.setStyleSheet(
                "background:#2A2113; color:#FFCE76; padding:7px 13px;"
                "border:1px solid #574321; border-radius:14px;"
            )
            self._set_chip(self.device_chip, "未连接", "warn")
            self._set_chip(self.sync_chip, "等待 TempoHub", "warn")
            return

        if state.get("running"):
            self.status.setText("TempoHub 已连接")
            self.status.setStyleSheet(
                "background:#121B16; color:#73E9A5; padding:7px 13px;"
                "border:1px solid #263E31; border-radius:14px;"
            )
        else:
            self.status.setText("歌词监听未启动")
            self.status.setStyleSheet(
                "background:#2A2113; color:#FFCE76; padding:7px 13px;"
                "border:1px solid #574321; border-radius:14px;"
            )

        song = state.get("song") or "等待播放音乐…"
        artist = state.get("artist") or "在网易云播放歌曲后会自动获取歌词"
        self.song_label.setText(song)
        self.artist_label.setText(artist)

        lyric = state.get("last_lyric") or "等待歌词…"
        if lyric != self.lyric_label.text():
            self.lyric_label.setText(lyric)
            self.preview.render_text(lyric if lyric != "等待歌词…" else "HALO PIXELBAR")

        progress = state.get("netease_progress") or {}
        position = progress.get("position")
        duration = progress.get("duration")
        self.current_time.setText(format_seconds(position))
        self.duration_time.setText(format_seconds(duration))
        if position is not None and duration:
            self.progress.setValue(
                max(0, min(1000, int(float(position) / float(duration) * 1000)))
            )
        else:
            self.progress.setValue(0)

        if position is not None:
            self._set_chip(self.sync_chip, "网易云精确同步", "good")
        else:
            error = progress.get("error") or "等待网易云播放器"
            self._set_chip(self.sync_chip, error, "warn")

        lyric_model = state.get("lyric_model") or {}
        if lyric_model.get("is_lyric_enabled"):
            self._set_chip(self.device_chip, "设备歌词已开启", "good")
            self._set_chip(self.device_state, "歌词模式运行中", "good")
        elif lyric_model.get("error"):
            self._set_chip(self.device_chip, "无法读取设备", "warn")
            self._set_chip(self.device_state, lyric_model["error"], "warn")
        else:
            self._set_chip(self.device_chip, "设备歌词未开启", "muted")
            self._set_chip(self.device_state, "可点击“重新开启歌词”", "muted")

        widgets = state.get("widgets") or {}
        audio = widgets.get("audio") or {}
        if audio.get("error"):
            self._set_chip(self.audio_status, audio["error"], "warn")
            self.audio_metrics.setText("系统音频不可用")
        elif audio.get("levels"):
            self._set_chip(self.audio_status, "系统音频监听中", "good")
            self.audio_metrics.setText(
                f"Peak {float(audio.get('peak_db', -80)):.1f} dB  ·  "
                f"RMS {float(audio.get('rms_db', -80)):.1f} dB"
            )

        notifications = widgets.get("notifications") or {}
        notification_status = notifications.get("status")
        notification_error = notifications.get("error")
        latest = notifications.get("latest") or {}
        if latest:
            self.notification_latest.setText(
                f"{latest.get('app', '通知')} · {latest.get('text', '')}"
            )
        elif notification_status:
            self.notification_latest.setText("暂无新通知")
        if notification_error:
            self._set_chip(
                self.notification_status,
                f"回退到窗口检测：{notification_error}",
                "warn",
            )
        elif notification_status:
            self._set_chip(
                self.notification_status,
                notification_status,
                "good"
                if ("监听" in notification_status or "检测" in notification_status)
                else "muted",
            )

        performance = widgets.get("performance") or {}
        fps = performance.get("fps")
        cpu = performance.get("cpu")
        gpu = performance.get("gpu")
        gpu_temp = performance.get("gpu_temp")
        memory = performance.get("memory")
        self.performance_values.setText(
            f"FPS {format_metric(fps)}  ·  CPU {format_metric(cpu)}%  ·  "
            f"GPU {format_metric(gpu)}% / {format_metric(gpu_temp)}°C  ·  "
            f"内存 {format_metric(memory)}%"
        )
        fps_status = performance.get("fps_status")
        fps_error = performance.get("fps_error")
        if fps_error:
            self._set_chip(self.fps_status, fps_error, "warn")
        elif fps_status:
            self._set_chip(
                self.fps_status,
                fps_status,
                "good" if fps_status == "采集中" else "muted",
            )


def main():
    ensure_tempo_hub_running()
    ensure_netease_running()
    app = QApplication(sys.argv)
    app.setApplicationName("Halo PixelBar 控制台")
    window = SettingsWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
