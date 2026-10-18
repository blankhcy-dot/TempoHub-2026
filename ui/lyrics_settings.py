from __future__ import annotations

import json
import os
import sys
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
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSlider,
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


def format_seconds(value):
    if value is None:
        return "--:--"
    value = max(0, int(value))
    return f"{value // 60:02d}:{value % 60:02d}"


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


class SettingsWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Halo PixelBar 歌词控制台")
        self.setMinimumSize(940, 610)
        self.resize(1040, 680)
        self.settings = {
            "enabled": True,
            "engine": "native",
            "line_offset_ms": 0,
        }
        self._suppress_offset_change = False
        self._build_ui()
        self.offset_apply_timer = QTimer(self)
        self.offset_apply_timer.setSingleShot(True)
        self.offset_apply_timer.setInterval(400)
        self.offset_apply_timer.timeout.connect(self._apply_offset)
        self._load_settings()
        self._refresh_state()
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._refresh_state)
        self.timer.start()

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
            QPushButton#quiet {
                background:transparent;
                border:0;
                color:#7E8A93;
                padding:5px 8px;
            }
            QPushButton#quiet:hover { color:#E8EDF0; }
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
        subtitle = QLabel("歌词控制台  ·  网易云精确同步")
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
        body.addWidget(preview_card, 3)

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
        body.addWidget(settings_card, 2)

        self.offset.valueChanged.connect(self._on_offset_changed)
        self.offset.sliderReleased.connect(self._apply_offset)
        self.reset_offset_btn.clicked.connect(lambda: self.offset.setValue(0))
        self.apply_btn.clicked.connect(self._apply)
        self.restore_btn.clicked.connect(self._restore_native)

    def _settings_payload(self, reapply_device=False):
        return {
            "enabled": True,
            "engine": "native",
            "line_offset_ms": self.offset.value(),
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
            self.device_state.setText("歌词模式已重新应用")
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


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Halo PixelBar 歌词控制台")
    window = SettingsWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
