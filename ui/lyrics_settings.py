from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from collections import deque
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

from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, QUrl, QVariantAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkReply, QNetworkRequest
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QKeySequence,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSlider,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


API_BASE = "http://127.0.0.1:47653"
PREVIEW_WIDTH = 256
PREVIEW_HEIGHT = 32


APPLE_STYLE = """
    QMainWindow, QWidget#windowShell, QWidget#root { background:transparent; }
    QWidget#titleBar { background:transparent; }
    QLabel#windowCaption { color:#6D737E; font-size:12px; font-weight:600; }
    QWidget { color:#1D1D1F; font-family:"Segoe UI", "Microsoft YaHei UI"; font-size:13px; }
    QWidget#scenePage, QWidget#content, QScrollArea > QWidget { background:#F5F5F7; }
    QLabel { background:transparent; border:0; }
    QFrame#card { background:#FFFFFF; border:1px solid #E0E2E7; border-radius:18px; }
    QFrame#divider { background:#ECEEF2; border:0; }
    QFrame#metricTile { background:#F7F9FC; border:1px solid #EAF0F7; border-radius:12px; }
    QLabel#metricTitle { color:#7B8390; font-size:11px; }
    QLabel#metricValue { color:#273446; font-size:23px; font-weight:600; }
    QLabel#eyebrow { color:#7A7D85; font-size:11px; font-weight:600; }
    QLabel#brand { color:#1D1D1F; font-size:19px; font-weight:700; }
    QLabel#pageTitle { color:#1D1D1F; font-size:27px; font-weight:700; }
    QLabel#subtitle, QLabel#pageSubtitle { color:#777B84; font-size:12px; }
    QLabel#section { color:#222329; font-size:15px; font-weight:600; }
    QLabel#songTitle { color:#1D1D1F; font-size:24px; font-weight:700; }
    QLabel#artist { color:#777B84; font-size:13px; }
    QLabel#lyric { color:#30333B; font-size:18px; font-weight:600; }
    QLabel#muted { color:#7B7F88; font-size:12px; }
    QLabel#offsetValue {
        background:#EDF4FF; color:#0066DD; border:0;
        border-radius:10px; padding:7px 12px; font-size:17px; font-weight:600;
    }
    QLabel#chipGood, QLabel#connection {
        background:#EAF6EE; color:#248347; border:0;
        border-radius:10px; padding:6px 10px; font-size:11px; font-weight:600;
    }
    QLabel#chipMuted {
        background:#F0F1F4; color:#737883; border:0;
        border-radius:10px; padding:6px 10px; font-size:11px;
    }
    QLabel#chipWarn {
        background:#FFF3E3; color:#A76513; border:0;
        border-radius:10px; padding:6px 10px; font-size:11px;
    }
    QProgressBar { background:#E9EBEF; border:0; border-radius:3px; min-height:5px; max-height:5px; }
    QProgressBar::chunk { background:#007AFF; border-radius:3px; }
    QSlider#offsetSlider { min-height:28px; }
    QSlider#offsetSlider::groove:horizontal { height:5px; background:#E4E7ED; border-radius:2px; }
    QSlider#offsetSlider::sub-page:horizontal { background:#007AFF; border-radius:2px; }
    QSlider#offsetSlider::handle:horizontal {
        width:19px; height:19px; margin:-7px 0;
        background:#FFFFFF; border:1px solid #CED3DC; border-radius:9px;
    }
    QSlider#offsetSlider::handle:horizontal:hover { border:1px solid #007AFF; }
    QPushButton {
        background:#FFFFFF; color:#414650; border:1px solid #DADDE3;
        border-radius:9px; padding:8px 14px; font-weight:600;
    }
    QPushButton:hover { background:#F4F6F9; border-color:#BCC5D2; }
    QPushButton:pressed { background:#E9EEF5; border-color:#8BB8F0; }
    QPushButton:disabled { color:#A3A8B1; background:#F4F5F7; border-color:#E7E9ED; }
    QPushButton:focus { border:1px solid #007AFF; }
    QPushButton#primary {
        background:#007AFF; color:#FFFFFF; border:1px solid #007AFF;
        border-radius:9px; padding:9px 18px;
    }
    QPushButton#primary:hover { background:#1685FF; border-color:#1685FF; }
    QPushButton#primary:pressed { background:#0065D6; border-color:#0065D6; }
    QPushButton#primary:disabled { background:#A4C9F5; border-color:#A4C9F5; color:#FFFFFF; }
    QPushButton:checked { background:#EDF4FF; color:#0068DE; border:1px solid #8DBEFF; }
    QPushButton#quiet { background:transparent; border:0; color:#007AFF; padding:6px 8px; }
    QPushButton#quiet:hover { background:#E5EFFF; color:#0066DD; }
    QFrame#navCard { background:#EBEDF2; border:1px solid #E0E3E9; border-radius:18px; }
    QLabel#navTitle { color:#9297A1; font-size:11px; font-weight:600; padding-left:8px; }
    QFrame#deviceSummary { background:#F6F7FA; border:1px solid #DFE3EB; border-radius:12px; }
    QLabel#deviceName { color:#4C535F; font-size:12px; font-weight:600; }
    QListWidget#sceneNav { background:transparent; border:0; outline:0; padding:0; }
    QListWidget#sceneNav::item {
        color:#4B515C; border:1px solid transparent;
        border-radius:9px; padding:10px 8px; margin:3px 0;
    }
    QListWidget#sceneNav::item:hover { background:#E0E5ED; color:#1D1D1F; }
    QListWidget#sceneNav::item:selected { background:#007AFF; color:#FFFFFF; border:1px solid #007AFF; }
    QScrollArea { background:transparent; border:0; }
    QScrollBar:vertical { background:transparent; width:7px; margin:5px 0; }
    QScrollBar::handle:vertical { background:#C4C8D0; border-radius:3px; min-height:28px; }
    QScrollBar::handle:vertical:hover { background:#A7ADB9; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
    QToolTip { color:#303640; background:#FFFFFF; border:1px solid #DDE2EB; padding:5px; }
"""


def scene_icon(kind, color):
    """Small code-drawn icons stay crisp without font or image dependencies."""
    pixmap = QPixmap(56, 56)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, 28, 28)
    gradient.setColorAt(0, QColor(color).lighter(112))
    gradient.setColorAt(1, QColor(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(QRectF(1, 1, 26, 26), 7, 7)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor("white"), 1.65, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if kind == "lyrics":
        painter.drawLine(QPointF(12, 19), QPointF(12, 9))
        painter.drawLine(QPointF(20, 17), QPointF(20, 7))
        painter.drawLine(QPointF(12, 9), QPointF(20, 7))
        painter.setBrush(QColor("white"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(7, 17, 5, 4))
        painter.drawEllipse(QRectF(15, 15, 5, 4))
    elif kind == "notifications":
        bubble = QPainterPath()
        bubble.addRoundedRect(QRectF(6, 7, 16, 12), 4, 4)
        painter.drawPath(bubble)
        painter.drawLine(QPointF(10, 19), QPointF(9, 22))
        painter.drawLine(QPointF(9, 22), QPointF(14, 19))
        for x in (10, 14, 18):
            painter.drawPoint(QPointF(x, 13))
    elif kind == "performance":
        path = QPainterPath(QPointF(6, 19))
        for x, y in ((10, 13), (14, 16), (18, 8), (22, 10)):
            path.lineTo(x, y)
        painter.drawPath(path)
    else:
        for y, x in ((8, 11), (14, 18), (20, 10)):
            painter.drawLine(QPointF(6, y), QPointF(22, y))
            painter.setBrush(QColor(color))
            painter.drawEllipse(QPointF(x, y), 2.5, 2.5)
    painter.end()
    icon = QIcon(pixmap)
    icon.addPixmap(pixmap, QIcon.Mode.Selected, QIcon.State.Off)
    return icon


class WindowControl(QPushButton):
    """Real window actions behind macOS-style traffic-light controls."""

    def __init__(self, kind, window):
        super().__init__()
        self.kind = kind
        self.host = window
        self.setFixedSize(24, 26)
        self.setObjectName("windowControl")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Native caption buttons do not take the content's initial keyboard focus.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        names = {"close": "关闭窗口", "minimize": "最小化窗口", "maximize": "最大化窗口"}
        self.setAccessibleName(names[kind])
        self.setToolTip(names[kind])
        self.clicked.connect({"close": window.close, "minimize": window.showMinimized,
                              "maximize": window._toggle_maximized}[kind])

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor({"close": "#FF5F57", "minimize": "#FEBC2E", "maximize": "#28C840"}[self.kind])
        if self.isDown():
            color = color.darker(112)
        painter.setPen(QPen(color.darker(110), 0.7))
        painter.setBrush(color)
        painter.drawEllipse(QRectF(5, 6, 14, 14))
        if self.underMouse() or self.hasFocus():
            painter.setPen(QPen(QColor("#5C3B32") if self.kind != "maximize" else QColor("#146524"),
                                1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            if self.kind == "close":
                painter.drawLine(QPointF(9.5, 10.5), QPointF(14.5, 15.5))
                painter.drawLine(QPointF(14.5, 10.5), QPointF(9.5, 15.5))
            elif self.kind == "minimize":
                painter.drawLine(QPointF(8.5, 13), QPointF(15.5, 13))
            else:
                painter.drawLine(QPointF(9, 16), QPointF(15, 10))
                painter.drawLine(QPointF(11.5, 10), QPointF(15, 10))
                painter.drawLine(QPointF(15, 10), QPointF(15, 13.5))
                painter.drawLine(QPointF(9, 12.5), QPointF(9, 16))
                painter.drawLine(QPointF(9, 16), QPointF(12.5, 16))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#8ABEFF"), 1))
            painter.drawEllipse(QRectF(2, 3, 20, 20))
        painter.end()


class WindowTitleBar(QWidget):
    def __init__(self, window):
        super().__init__()
        self.host = window
        self._drag_offset = None
        self._press_global = None
        self._press_fraction = 0.5
        self.setObjectName("titleBar")
        self.setFixedHeight(38)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 3, 12, 3)
        controls = QHBoxLayout()
        controls.setSpacing(0)
        self.close_button = WindowControl("close", window)
        self.minimize_button = WindowControl("minimize", window)
        self.maximize_button = WindowControl("maximize", window)
        for button in (self.close_button, self.minimize_button, self.maximize_button):
            controls.addWidget(button)
        layout.addLayout(controls)
        layout.addStretch(1)
        caption = QLabel("Halo PixelBar")
        caption.setObjectName("windowCaption")
        caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(caption)
        layout.addStretch(1)
        layout.addSpacing(72)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._press_fraction = event.position().x() / max(1, self.width())
            handle = self.host.windowHandle()
            if handle is None or not handle.startSystemMove():
                self._drag_offset = self._press_global - self.host.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            position = event.globalPosition().toPoint()
            if self.host.isMaximized():
                if (position - self._press_global).manhattanLength() < QApplication.startDragDistance():
                    return
                self.host.showNormal()
                self._drag_offset = QPoint(round(self.host.width() * self._press_fraction), self.height() // 2)
            self.host.move(position - self._drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        self._press_global = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            self.host._toggle_maximized()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class WindowShell(QWidget):
    """One rounded surface, including the title bar; no full-window blur effect."""

    def __init__(self):
        super().__init__()
        self.setObjectName("windowShell")
        self.inset = 6

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(self.inset + 0.5, self.inset + 0.5,
                                          -self.inset - 0.5, -self.inset - 0.5)
        radius = 17 if self.inset else 0
        if self.inset:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for distance in range(5, 0, -1):
                painter.setPen(QPen(QColor(30, 40, 60, 3 + (5 - distance) * 2), 1))
                painter.drawRoundedRect(rect.adjusted(-distance, -distance, distance, distance),
                                        radius + distance, radius + distance)
        painter.setPen(QPen(QColor("#D9DDE5"), 1))
        painter.setBrush(QColor("#F5F5F7"))
        painter.drawRoundedRect(rect, radius, radius)
        painter.end()


class WindowResizeHandle(QWidget):
    def __init__(self, window, edges, cursor):
        super().__init__(window)
        self.host = window
        self.edges = edges
        self._press_global = None
        self._press_rect = None
        self.setCursor(cursor)
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        handle = self.host.windowHandle()
        if handle is None or not handle.startSystemResize(self.edges):
            self._press_global = event.globalPosition().toPoint()
            self._press_rect = QRect(self.host.geometry())
        event.accept()

    def mouseMoveEvent(self, event):
        if self._press_global is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return super().mouseMoveEvent(event)
        delta = event.globalPosition().toPoint() - self._press_global
        rect = self._press_rect
        left, top = rect.x(), rect.y()
        right, bottom = left + rect.width(), top + rect.height()
        if self.edges & Qt.Edge.LeftEdge:
            left = min(right - self.host.minimumWidth(), left + delta.x())
        if self.edges & Qt.Edge.RightEdge:
            right = max(left + self.host.minimumWidth(), right + delta.x())
        if self.edges & Qt.Edge.TopEdge:
            top = min(bottom - self.host.minimumHeight(), top + delta.y())
        if self.edges & Qt.Edge.BottomEdge:
            bottom = max(top + self.host.minimumHeight(), bottom + delta.y())
        self.host.setGeometry(left, top, right - left, bottom - top)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._press_global = None
        self._press_rect = None
        super().mouseReleaseEvent(event)


class SettingsSwitch(QCheckBox):
    """An accessible checkbox with a compact, animated switch presentation."""

    def __init__(self, text):
        super().__init__(text)
        self._position = 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(140)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._animate)
        self.toggled.connect(self._toggle)
        self.setMinimumHeight(38)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self):
        return QSize(max(150, self.fontMetrics().horizontalAdvance(self.text()) + 60), 38)

    def hitButton(self, point):
        return self.rect().contains(point)

    def _toggle(self, checked):
        self._animation.stop()
        if not self.isVisible() or self.signalsBlocked():
            self._animate(1.0 if checked else 0.0)
            return
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def checkStateSet(self):
        super().checkStateSet()
        if hasattr(self, "_animation") and (self.signalsBlocked() or not self.isVisible()):
            self._animation.stop()
            self._animate(1.0 if self.isChecked() else 0.0)

    def _animate(self, value):
        self._position = float(value)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(1.0 if self.isEnabled() else 0.45)
        painter.setFont(self.font())
        painter.setPen(QColor("#3A414C"))
        painter.drawText(self.rect().adjusted(0, 0, -52, 0),
                         int((Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter).value), self.text())
        track = QRectF(self.width() - 39, (self.height() - 22) / 2, 38, 22)
        off, on = QColor("#D5D9E1"), QColor("#007AFF")
        mix = self._position
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(*[round(off.getRgb()[i] * (1 - mix) + on.getRgb()[i] * mix) for i in range(3)]))
        painter.drawRoundedRect(track, 11, 11)
        painter.setBrush(QColor(0, 0, 0, 18))
        knob_x = track.left() + 2 + 16 * mix
        painter.drawEllipse(QRectF(knob_x, track.top() + 3, 18, 18))
        painter.setBrush(QColor("white"))
        painter.drawEllipse(QRectF(knob_x, track.top() + 2, 18, 18))
        if self.hasFocus():
            painter.setPen(QPen(QColor("#8ABEFF"), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(track.adjusted(-2, -2, 2, 2), 13, 13)
        painter.end()


class ApiClient(QObject):
    """Keep HTTP off the GUI thread, with ordered writes and bounded polling."""

    writes_finished = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = QNetworkAccessManager(self)
        self.manager.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        self._reads = set()
        self._writes = deque()
        self._writing = False
        self._closed = False
        self._replies = set()
        self._write_failed = False

    def has_pending_writes(self):
        return self._writing or bool(self._writes)

    def last_write_failed(self):
        return self._write_failed

    def get(self, path, callback, timeout=3.0):
        if self._closed or path in self._reads:
            return
        self._reads.add(path)
        self._request(path, None, callback, timeout)

    def post(self, path, payload, callback, timeout=5.0, coalesce=None, followup=False):
        if self._closed:
            return
        if not self.has_pending_writes():
            self._write_failed = False
        # Copy now so later widget changes cannot alter a queued command.
        command = (path, json.dumps(payload, ensure_ascii=False).encode("utf-8"), callback, timeout, coalesce)
        # Only collapse adjacent edits; never move an edit across an action.
        if followup:
            # A dependent action completes the in-flight command before later
            # user commands (e.g. switch scene, send test, then switch again).
            self._writes.appendleft(command)
        elif coalesce and self._writes and self._writes[-1][4] == coalesce:
            self._writes[-1] = command
        elif len(self._writes) >= 32:
            self._write_failed = True
            callback(None, RuntimeError("操作较多，请稍候再试"))
            return
        else:
            self._writes.append(command)
        self._next_write()

    def _next_write(self):
        if self._closed or self._writing or not self._writes:
            return
        self._writing = True
        self._request(*self._writes.popleft()[:4])

    def _request(self, path, body, callback, timeout):
        request = QNetworkRequest(QUrl(API_BASE + path))
        if body is None:
            reply = self.manager.get(request)
        else:
            request.setRawHeader(b"Content-Type", b"application/json; charset=utf-8")
            reply = self.manager.post(request, body)
        self._replies.add(reply)
        timer = QTimer(reply)
        timer.setSingleShot(True)
        timer.timeout.connect(reply.abort)
        timer.start(max(1, int(timeout * 1000)))

        def finished():
            timer.stop()
            self._replies.discard(reply)
            result, error = None, None
            try:
                raw = bytes(reply.readAll())
                try:
                    result = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeError):
                    result = None
                if reply.error() != QNetworkReply.NetworkError.NoError:
                    message = result.get("error") if isinstance(result, dict) else None
                    raise RuntimeError(message or reply.errorString())
                if not isinstance(result, dict):
                    raise ValueError("TempoHub 返回的数据格式无效")
            except Exception as failure:
                error = failure
            finally:
                reply.deleteLater()
                if body is None:
                    self._reads.discard(path)
            try:
                if not self._closed:
                    callback(result, error)
            finally:
                if body is not None:
                    self._write_failed = self._write_failed or error is not None
                    self._writing = False
                    self._next_write()
                    if not self.has_pending_writes() and not self._closed:
                        self.writes_finished.emit(self._write_failed)

        reply.finished.connect(finished)

    def close(self):
        self._closed = True
        self._writes.clear()
        for reply in tuple(self._replies):
            reply.abort()


class StartupBridge(QObject):
    ready = pyqtSignal()


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


class ScaledPreview(QLabel):
    """Scale the original image on resize without stretching the layout."""

    def __init__(self, width=512, height=96):
        super().__init__()
        self._source_pixmap = None
        self._preview_height = height
        self.setMinimumWidth(256)
        self.setMaximumWidth(width)
        self.setFixedHeight(height)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def setPixmap(self, pixmap):
        self._source_pixmap = pixmap
        self._fit_pixmap()

    def _fit_pixmap(self):
        if self._source_pixmap is not None:
            super().setPixmap(self._source_pixmap.scaled(
                max(1, self.width() - 16), self._preview_height - 12,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            ))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_pixmap()


class LyricPreview(ScaledPreview):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "background:#101114; border:1px solid #20232A; border-radius:14px;"
        )
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 5)
        shadow.setColor(QColor(25, 35, 55, 28))
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




class ToneCurvePreview(ScaledPreview):
    def __init__(self):
        super().__init__(520, 230)
        self.setStyleSheet(
            "background:#F8FAFD; border:1px solid #E8ECF2; border-radius:14px;"
        )
        self.mode = 0
        self.render_curve()

    def set_mode(self, mode):
        self.mode = max(0, min(2, int(mode)))
        self.render_curve()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "mode"):
            self.render_curve()

    def render_curve(self):
        width, height = max(240, self.width() - 16), self._preview_height - 12
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(QColor("#F8FAFD"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        plot = QRectF(32, 36, width - 54, height - 82)
        painter.setPen(QPen(QColor("#E0E6EF"), 1))
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
            0: QColor("#007AFF"),
            1: QColor("#AF52DE"),
            2: QColor("#F1972C"),
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
        fill = QPainterPath(path)
        fill.lineTo(plot.right(), plot.bottom())
        fill.lineTo(plot.left(), plot.bottom())
        fill.closeSubpath()
        shading = QLinearGradient(0, plot.top(), 0, plot.bottom())
        tint = QColor(colors[self.mode])
        tint.setAlpha(40)
        shading.setColorAt(0, tint)
        tint.setAlpha(2)
        shading.setColorAt(1, tint)
        painter.fillPath(fill, shading)
        painter.setPen(QPen(colors[self.mode], 2.5))
        painter.drawPath(path)
        labels = ("60", "250", "1k", "3k", "8k", "16k")
        painter.setFont(QFont("Consolas", 8))
        painter.setPen(QColor("#7D8796"))
        for index, label in enumerate(labels):
            x = plot.left() + plot.width() * index / (len(labels) - 1)
            painter.drawText(QRectF(x - 24, plot.bottom() + 8, 48, 18), int(Qt.AlignmentFlag.AlignCenter.value), label)
        painter.drawText(
            QRectF(12, 5, width - 24, 18),
            int(Qt.AlignmentFlag.AlignLeft.value),
            "调音设计意图 · 非设备频响实测",
        )
        painter.end()
        self.setPixmap(QPixmap.fromImage(image))


class SettingsWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Halo PixelBar 控制台")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowMinMaxButtonsHint
                            | Qt.WindowType.WindowCloseButtonHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(960, 620)
        self.resize(1180, 760)
        self.settings = {
            "enabled": True,
            "engine": "native",
            "line_offset_ms": 0,
            "scene": "lyrics",
            "sound_mode": 0,
        }
        self._suppress_offset_change = False
        self._suppress_scene_change = True
        self._settings_loaded = False
        self._connected = False
        self._poll_failures = 0
        self._scene_revision = 0
        self._edit_revision = 0
        self._close_pending = False
        self._allow_close = False
        self._force_close_revision = None
        self._progress_sample = None
        self.api = ApiClient(self)
        self._build_ui()
        self._build_resize_handles()
        self._close_shortcut = QShortcut(QKeySequence("Alt+F4"), self)
        self._close_shortcut.activated.connect(self.close)
        self.offset_apply_timer = QTimer(self)
        self.offset_apply_timer.setSingleShot(True)
        self.offset_apply_timer.setInterval(400)
        self.offset_apply_timer.timeout.connect(self._apply_offset)
        self._populate_settings()
        self._suppress_scene_change = False
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._refresh_state)
        self.timer.start()
        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(80)
        self.progress_timer.timeout.connect(self._animate_progress)
        self.progress_timer.start()
        self.close_wait_timer = QTimer(self)
        self.close_wait_timer.setSingleShot(True)
        self.close_wait_timer.setInterval(5000)
        self.close_wait_timer.timeout.connect(self._close_save_timeout)
        self.api.writes_finished.connect(self._finish_pending_close)
        QTimer.singleShot(0, self._load_settings)
        QTimer.singleShot(0, self._refresh_state)

    def _card(self):
        card = QFrame()
        card.setObjectName("card")
        return card

    def _divider(self):
        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        return divider

    def _build_resize_handles(self):
        definitions = {
            "left": (Qt.Edge.LeftEdge, Qt.CursorShape.SizeHorCursor),
            "right": (Qt.Edge.RightEdge, Qt.CursorShape.SizeHorCursor),
            "top": (Qt.Edge.TopEdge, Qt.CursorShape.SizeVerCursor),
            "bottom": (Qt.Edge.BottomEdge, Qt.CursorShape.SizeVerCursor),
            "top_left": (Qt.Edge.TopEdge | Qt.Edge.LeftEdge, Qt.CursorShape.SizeFDiagCursor),
            "top_right": (Qt.Edge.TopEdge | Qt.Edge.RightEdge, Qt.CursorShape.SizeBDiagCursor),
            "bottom_left": (Qt.Edge.BottomEdge | Qt.Edge.LeftEdge, Qt.CursorShape.SizeBDiagCursor),
            "bottom_right": (Qt.Edge.BottomEdge | Qt.Edge.RightEdge, Qt.CursorShape.SizeFDiagCursor),
        }
        self.resize_handles = {name: WindowResizeHandle(self, edges, cursor)
                               for name, (edges, cursor) in definitions.items()}
        self._update_window_chrome()

    def _toggle_maximized(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _update_window_chrome(self):
        if not hasattr(self, "resize_handles"):
            return
        expanded = self.isMaximized() or self.isFullScreen()
        inset = 0 if expanded else 6
        self.window_shell.inset = inset
        self.shell_layout.setContentsMargins(inset, inset, inset, inset)
        self.window_shell.update()
        action = "还原窗口" if expanded else "最大化窗口"
        self.title_bar.maximize_button.setAccessibleName(action)
        self.title_bar.maximize_button.setToolTip(action)
        self.title_bar.maximize_button.update()
        width, height, edge, corner = self.width(), self.height(), 8, 14
        geometry = {
            "left": (0, corner, edge, max(0, height - 2 * corner)),
            "right": (width - edge, corner, edge, max(0, height - 2 * corner)),
            "top": (corner, 0, max(0, width - 2 * corner), edge),
            "bottom": (corner, height - edge, max(0, width - 2 * corner), edge),
            "top_left": (0, 0, corner, corner),
            "top_right": (width - corner, 0, corner, corner),
            "bottom_left": (0, height - corner, corner, corner),
            "bottom_right": (width - corner, height - corner, corner, corner),
        }
        for name, handle in self.resize_handles.items():
            handle.setGeometry(*geometry[name])
            handle.setVisible(not expanded)
            handle.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_window_chrome()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._update_window_chrome()

    def _set_content_enabled(self, enabled):
        # The custom window controls must remain usable during a pending save.
        self.content_root.setEnabled(enabled)

    def _build_ui(self):
        self.setStyleSheet(APPLE_STYLE)

        self.window_shell = WindowShell()
        self.setCentralWidget(self.window_shell)
        self.shell_layout = QVBoxLayout(self.window_shell)
        self.shell_layout.setContentsMargins(6, 6, 6, 6)
        self.shell_layout.setSpacing(0)
        self.title_bar = WindowTitleBar(self)
        self.shell_layout.addWidget(self.title_bar)
        root = QWidget()
        root.setObjectName("root")
        self.content_root = root
        self.shell_layout.addWidget(root, 1)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(14, 14, 20, 14)
        outer.setSpacing(22)
        content = QWidget()
        content.setObjectName("content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 8, 0, 2)
        content_layout.setSpacing(18)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(4)
        self.page_title = QLabel("歌词同步")
        self.page_title.setObjectName("pageTitle")
        self.page_subtitle = QLabel("让每一句歌词，与此刻同步。")
        self.page_subtitle.setObjectName("pageSubtitle")
        heading.addWidget(self.page_title)
        heading.addWidget(self.page_subtitle)
        header.addLayout(heading, 1)
        header.addStretch()
        self.status = QLabel("正在连接 TempoHub…")
        self.status.setObjectName("connection")
        header.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        self.reconnect_btn = QPushButton("重新连接")
        self.reconnect_btn.setObjectName("quiet")
        self.reconnect_btn.setToolTip("立即重新读取 TempoHub 状态和设置")
        self.reconnect_btn.clicked.connect(self._reconnect)
        header.addWidget(self.reconnect_btn)
        content_layout.addLayout(header)

        nav_card = QFrame()
        nav_card.setObjectName("navCard")
        nav_card.setFixedWidth(204)
        nav_layout = QVBoxLayout(nav_card)
        nav_layout.setContentsMargins(12, 22, 12, 14)
        nav_layout.setSpacing(14)
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(6, 0, 2, 14)
        brand_mark = QLabel()
        brand_mark.setPixmap(scene_icon("lyrics", "#007AFF").pixmap(QSize(36, 36)))
        brand_mark.setFixedSize(38, 38)
        brand_row.addWidget(brand_mark)
        brand_box = QVBoxLayout()
        brand_box.setSpacing(1)
        brand = QLabel("TempoHub")
        brand.setObjectName("brand")
        subtitle = QLabel("Halo PixelBar")
        subtitle.setObjectName("subtitle")
        brand_box.addWidget(brand)
        brand_box.addWidget(subtitle)
        brand_row.addLayout(brand_box, 1)
        nav_layout.addLayout(brand_row)
        nav_title = QLabel("设备与场景")
        nav_title.setObjectName("navTitle")
        nav_layout.addWidget(nav_title)
        self.nav = QListWidget()
        self.nav.setObjectName("sceneNav")
        self.nav.setIconSize(QSize(24, 24))
        for text, kind, color in (("歌词同步", "lyrics", "#F45C81"),
                                  ("音效调优", "sound", "#007AFF")):
            self.nav.addItem(QListWidgetItem(scene_icon(kind, color), text))
        self.nav.setCurrentRow(0)
        nav_layout.addWidget(self.nav, 1)
        self.nav_state = QLabel("正在读取设备场景…")
        self.nav_state.setObjectName("muted")
        self.nav_state.setWordWrap(True)
        device_summary = QFrame()
        device_summary.setObjectName("deviceSummary")
        device_layout = QVBoxLayout(device_summary)
        device_layout.setContentsMargins(12, 12, 12, 12)
        device_layout.setSpacing(5)
        device_name = QLabel("HALO PIXELBAR")
        device_name.setObjectName("deviceName")
        device_layout.addWidget(device_name)
        device_layout.addWidget(self.nav_state)
        nav_layout.addWidget(device_summary)
        outer.addWidget(nav_card)
        outer.addWidget(content, 1)

        self.pages = QStackedWidget()
        content_layout.addWidget(self.pages, 1)
        self.lyrics_page = QWidget()
        lyrics_page_layout = QHBoxLayout(self.lyrics_page)
        lyrics_page_layout.setContentsMargins(0, 0, 0, 0)
        lyrics_page_layout.setSpacing(16)
        self.pages.addWidget(self.lyrics_page)

        preview_card = self._card()
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(24, 24, 24, 24)
        preview_layout.setSpacing(16)

        eyebrow = QLabel("设备实时预览")
        eyebrow.setObjectName("eyebrow")
        preview_layout.addWidget(eyebrow)
        self.preview = LyricPreview()
        preview_layout.addWidget(self.preview)

        self.song_label = QLabel("等待播放音乐…")
        self.song_label.setObjectName("songTitle")
        self.song_label.setWordWrap(True)
        preview_layout.addWidget(self.song_label)
        self.artist_label = QLabel("在网易云播放歌曲后会自动获取歌词")
        self.artist_label.setObjectName("artist")
        self.artist_label.setWordWrap(True)
        preview_layout.addWidget(self.artist_label)
        preview_layout.addWidget(self._divider())

        lyric_eyebrow = QLabel("当前歌词")
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
        chip_row.addWidget(self.device_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        chip_row.addWidget(self.sync_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        chip_row.addStretch()
        preview_layout.addLayout(chip_row)
        lyrics_page_layout.addWidget(preview_card, 3)

        settings_card = self._card()
        settings_layout = QVBoxLayout(settings_card)
        settings_layout.setContentsMargins(24, 22, 24, 20)
        settings_layout.setSpacing(12)

        settings_eyebrow = QLabel("同步调节")
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
        self.apply_btn = QPushButton("应用显示")
        self.apply_btn.setObjectName("primary")
        actions.addWidget(self.restore_btn)
        actions.addStretch()
        actions.addWidget(self.apply_btn)
        settings_layout.addLayout(actions)
        lyrics_page_layout.addWidget(settings_card, 2)

        self.sound_page = self._build_sound_page()
        self.pages.addWidget(self.sound_page)

        self.offset.valueChanged.connect(self._on_offset_changed)
        self.offset.sliderReleased.connect(self._apply_offset)
        self.reset_offset_btn.clicked.connect(lambda: self.offset.setValue(0))
        self.apply_btn.clicked.connect(self._apply)
        self.restore_btn.clicked.connect(self._restore_native)
        self.nav.currentRowChanged.connect(self._switch_scene)

        # Keep every control reachable on smaller displays and at high DPI.
        for page in (self.lyrics_page, self.sound_page):
            page.setObjectName("scenePage")
            index = self.pages.indexOf(page)
            self.pages.removeWidget(page)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(page)
            self.pages.insertWidget(index, scroll)
        self.pages.setCurrentIndex(0)

        footer = QHBoxLayout()
        self.feedback = QLabel("就绪后，选择场景即可投送到设备")
        self.feedback.setObjectName("subtitle")
        self.feedback.setWordWrap(True)
        footer.addWidget(self.feedback, 1)
        matrix_hint = QLabel("音响原生显示")
        matrix_hint.setObjectName("eyebrow")
        footer.addWidget(matrix_hint)
        content_layout.addLayout(footer)
        for label in self.findChildren(QLabel):
            label.setTextFormat(Qt.TextFormat.PlainText)
        for button in self.findChildren(QPushButton):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.offset.setAccessibleName("歌词时间偏移，单位毫秒")

    def _build_sound_page(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        preview_card = self._card()
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(26, 22, 26, 22)
        preview_layout.setSpacing(12)
        eyebrow = QLabel("硬件音效")
        eyebrow.setObjectName("eyebrow")
        preview_layout.addWidget(eyebrow)
        title = QLabel("音效概览")
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
        control_eyebrow = QLabel("聆听模式")
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
        sound_display = QPushButton("返回歌词显示")
        sound_display.setObjectName("primary")
        sound_display.clicked.connect(lambda: self._activate_scene_page(0))
        controls_layout.addWidget(sound_display)
        layout.addWidget(controls, 2)
        return page

    def _load_eq_capability(self):
        def loaded(info, error):
            if error:
                self._set_chip(self.sound_capability, "设备 EQ 暂不可用", "warn")
                self.sound_capability.setToolTip(str(error))
                return
            eq_index = info.get("eq_index")
            probe = info.get("custom_eq_probe") or {}
            custom_supported = probe.get("supported")
            text = f"硬件 EQ 类型 {eq_index} · 3 个预设"
            if custom_supported is None:
                self._set_chip(self.sound_capability, "设备 EQ 能力待确认", "warn")
                self.sound_capability.setToolTip(probe.get("error") or "设备尚未返回能力信息")
                return
            text += " · 支持自定义 EQ" if custom_supported else " · 不支持自定义频段"
            self.sound_capability.setToolTip("")
            self._set_chip(
                self.sound_capability,
                text,
                "good" if custom_supported else "muted",
            )
        self.api.get("/api/eq/info", loaded, timeout=4.0)

    def _set_sound_mode(self, index):
        self._edit_revision += 1
        self._set_chip(self.sound_status, "正在切换硬件模式…", "muted")
        for button in self.sound_buttons:
            button.setEnabled(False)

        def applied(result, error):
            for button in self.sound_buttons:
                button.setEnabled(True)
            if error:
                previous = int(self.settings.get("sound_mode", 0))
                self.sound_buttons[max(0, min(2, previous))].setChecked(True)
                self._set_chip(self.sound_status, "模式切换失败，请重试", "warn")
                self.sound_status.setToolTip(str(error))
                return
            self.settings["sound_mode"] = index
            self.sound_buttons[index].setChecked(True)
            self.sound_curve.set_mode(index)
            self._set_sound_mode_label(index)
            self.sound_status.setToolTip("")
            self._set_chip(self.sound_status, "模式设置已发送" if result.get("status") == "queued" else "硬件模式已切换", "good")
        # The preset endpoint already persists sound_mode.
        self.api.post("/api/eq/preset", {"index": index}, applied)

    def _selected_scene(self):
        return "lyrics"

    def _switch_scene(self, row):
        if not 0 <= row < 2:
            return
        self.pages.setCurrentIndex(row)
        self.page_title.setText(("歌词同步", "音效调优")[row])
        self.page_subtitle.setText(("让每一句歌词，与此刻同步。", "为不同的时刻，找到合适的声音。")[row])
        self._scene_revision += 1
        if row == 1:
            self._load_eq_capability()
        elif not self._suppress_scene_change and self._settings_loaded:
            self._apply_scene_options()

    def _apply_scene_options(self, _checked=False, on_success=None, reapply_device=True, on_failure=None):
        if not self._settings_loaded:
            self.feedback.setText("正在读取设置，连接后可应用场景")
            if on_failure:
                on_failure(RuntimeError("正在等待 TempoHub 连接"))
            return
        self._edit_revision += 1
        edit_revision = self._edit_revision
        payload = self._settings_payload(reapply_device=reapply_device)
        scene = payload["scene"]
        revision = self._scene_revision
        self.feedback.setText("正在应用显示场景…")

        def applied(result, error):
            if not error and (reapply_device or result.get("applied")) and not (result.get("display") or {}).get("verified"):
                error = RuntimeError("设置已保存，但音响尚未确认显示")
            if error:
                self.feedback.setText("场景应用失败，请检查连接后重试")
                self.feedback.setToolTip(str(error))
                if on_failure:
                    on_failure(error)
                return
            self.settings.update(result.get("settings", {}))
            confirmed = bool((result.get("display") or {}).get("verified") and result.get("applied", True))
            if confirmed:
                self._update_active_scene(scene)
            if revision == self._scene_revision and edit_revision == self._edit_revision:
                self.feedback.setText("音响已确认显示，设置已保存" if confirmed else "设置已自动保存")
            if on_success:
                on_success()
        self.api.post("/api/settings", payload, applied, timeout=12.0,
                      coalesce=None if on_success else "scene-settings")

    def _update_active_scene(self, scene):
        self.nav_state.setText("设备场景 · " + ("歌词同步" if scene == "lyrics" else "等待确认"))




    def _activate_scene_page(self, row, on_success=None, on_failure=None):
        self._suppress_scene_change = True
        self.nav.setCurrentRow(row)
        self.pages.setCurrentIndex(row)
        self._suppress_scene_change = False
        self._apply_scene_options(on_success=on_success, on_failure=on_failure)




    def _settings_payload(self, reapply_device=False):
        return {"enabled": True, "scene": self._selected_scene(), "engine": "native",
                "line_offset_ms": self.offset.value(),
                "reapply_device": bool(reapply_device)}

    def _set_offset(self, milliseconds):
        self._suppress_offset_change = True
        self.offset.setValue(int(milliseconds))
        self.offset_value.setText(format_offset(milliseconds))
        self._suppress_offset_change = False

    def _load_settings(self):
        revision = self._edit_revision

        def loaded(settings, error):
            if error:
                self.feedback.setText("等待 TempoHub 连接，窗口会自动重试")
                return
            if self._settings_loaded and (revision != self._edit_revision or self._has_pending_edits()):
                return
            if self._settings_loaded and self.api.last_write_failed():
                self.feedback.setText("有操作未保存，已保留当前设置，请重新应用。")
                return
            initial_load = not self._settings_loaded
            self.settings.update(settings)
            self._suppress_scene_change = True
            try:
                self._populate_settings(select_scene=initial_load)
                self._settings_loaded = True
            finally:
                self._suppress_scene_change = False
            self._update_active_scene(self.settings.get("scene", "lyrics"))
            self.feedback.setText("设置已载入 · 调整后自动保存")
        self.api.get("/api/settings", loaded)

    def _populate_settings(self, select_scene=True):
        scene = self.settings.get("scene", "lyrics")
        if scene != "lyrics":
            self.settings["scene"] = "lyrics"
        self._set_offset(int(self.settings.get("line_offset_ms", 0)))
        sound_mode = max(0, min(2, int(self.settings.get("sound_mode", 0))))
        self.sound_buttons[sound_mode].setChecked(True)
        self.sound_curve.set_mode(sound_mode)
        self._set_sound_mode_label(sound_mode)
        if select_scene:
            self.nav.setCurrentRow(0)
            self.pages.setCurrentIndex(0)

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
        if not self._suppress_offset_change and self._settings_loaded:
            self._edit_revision += 1
            self.offset_apply_timer.start()

    def _apply_offset(self):
        self.offset_apply_timer.stop()
        if not self._settings_loaded:
            return
        self._edit_revision += 1
        value = self.offset.value()
        self.feedback.setText("正在保存歌词偏移…")

        def saved(result, error):
            if error:
                self.feedback.setText("偏移保存失败，请重试")
                self.feedback.setToolTip(str(error))
                return
            self.settings.update(result.get("settings", {}))
            if self.offset.value() == value:
                self.feedback.setText(f"歌词偏移 {format_offset(value)} · 已保存")
        self.api.post("/api/settings", {"line_offset_ms": value, "reapply_device": False},
                      saved, coalesce="lyric-offset")

    def _apply(self):
        self.offset_apply_timer.stop()
        self._apply_scene_options()

    def _restore_native(self):
        self._edit_revision += 1
        self.offset_apply_timer.stop()
        self.restore_btn.setEnabled(False)
        self.feedback.setText("正在重新开启设备歌词…")
        revision = self._scene_revision

        def restored(result, error):
            self.restore_btn.setEnabled(True)
            if not error and not (result.get("display") or {}).get("verified"):
                error = RuntimeError("音响尚未确认开启歌词")
            if error:
                self.feedback.setText("重新开启歌词失败，请重试")
                self.feedback.setToolTip(str(error))
                return
            self.settings.update(result.get("settings", {}))
            self._update_active_scene("lyrics")
            if revision == self._scene_revision:
                self._suppress_scene_change = True
                self.nav.setCurrentRow(0)
                self._suppress_scene_change = False
                self.feedback.setText("已重新开启设备歌词")
        self.api.post("/api/restore-native", {}, restored, timeout=12.0)

    def _set_chip(self, label, text, state):
        names = {
            "good": "chipGood",
            "muted": "chipMuted",
            "warn": "chipWarn",
        }
        text = str(text)
        summary = text if len(text) <= 120 else text[:117] + "…"
        # QLabel's word wrapping does not break long URL/error tokens by itself.
        wrapped = re.sub(r"\S{17,}", lambda match: "\u200b".join(
            match.group()[index:index + 16] for index in range(0, len(match.group()), 16)), summary)
        label.setWordWrap(True)
        label.setText(wrapped)
        label.setToolTip(text if wrapped != text else "")
        if label.objectName() != names[state]:
            label.setObjectName(names[state])
            label.style().unpolish(label)
            label.style().polish(label)

    def _has_pending_edits(self):
        return self.offset_apply_timer.isActive() or self.api.has_pending_writes()

    def _finish_pending_close(self, failed):
        if not self._close_pending:
            return
        self.close_wait_timer.stop()
        if failed:
            self._close_pending = False
            self._force_close_revision = self._edit_revision
            self._set_content_enabled(True)
            self.feedback.setText("保存失败，窗口已保留。请重试或再次关闭。")
            return
        self._allow_close = True
        self.close()

    def _close_save_timeout(self):
        if self._close_pending:
            self._close_pending = False
            self._force_close_revision = self._edit_revision
            self._set_content_enabled(True)
            self.feedback.setText("保存尚未完成，请稍候再关闭。")

    def closeEvent(self, event):
        force_requested = self._force_close_revision == self._edit_revision
        if not self._allow_close and not force_requested and not self._close_pending and self._has_pending_edits():
            event.ignore()
            self._close_pending = True
            self._set_content_enabled(False)
            self.close_wait_timer.start()
            pending_offset = self.offset_apply_timer.isActive()
            if pending_offset:
                self._apply_offset()
            self.feedback.setText("正在保存设置，完成后关闭…")
            return
        # A second close explicitly exits even if a service is unresponsive.
        self._allow_close = True
        self.close_wait_timer.stop()
        self.timer.stop()
        self.progress_timer.stop()
        self.offset_apply_timer.stop()
        self.api.close()
        super().closeEvent(event)

    def _refresh_state(self):
        self.api.get("/api/state", self._state_received, timeout=2.0)

    def _reconnect(self):
        self.feedback.setText("正在重新连接…")
        self._refresh_state()
        self._load_settings()

    def _state_received(self, state, error):
        recovered = error is None and self._poll_failures > 0
        self._connected = error is None
        if error:
            self._poll_failures = min(3, self._poll_failures + 1)
            self.timer.setInterval(1000 * 2 ** self._poll_failures)
            self._set_chip(self.status, "连接中断 · 自动重试中", "warn")
            self.status.setToolTip(str(error))
            self._set_chip(self.device_chip, "未连接", "warn")
            self._set_chip(self.device_state, "等待 TempoHub 连接", "warn")
            self._set_chip(self.sync_chip, "等待 TempoHub", "warn")
            self._progress_sample = None
            return
        self._poll_failures = 0
        if recovered:
            self.feedback.setText("连接已恢复 · 未完成的操作可重新应用")
            self.feedback.setToolTip("")
        self.timer.setInterval(5000 if self.isMinimized() else 1000)
        self.status.setToolTip("")
        display = state.get("display")
        device_connected = display.get("connected", False) if isinstance(display, dict) else state.get("running")
        self._set_chip(self.status, "TempoHub 已连接" if device_connected else "等待设备连接",
                       "good" if device_connected else "warn")
        if recovered or not self._settings_loaded:
            self._load_settings()
        if isinstance(display, dict):
            if display.get("verified") and display.get("scene"):
                self._update_active_scene(display["scene"])
            else:
                self.nav_state.setText("设备场景 · 等待确认")
        else:
            self._update_active_scene(state.get("scene", self.settings.get("scene", "lyrics")))

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
        sync_failed = bool(progress.get("error") or progress.get("stale"))
        self._progress_sample = (position, duration, bool(state.get("is_playing")) and not sync_failed, time.monotonic())
        self._animate_progress()
        self.duration_time.setText(format_seconds(duration))

        if sync_failed:
            self._set_chip(self.sync_chip, progress.get("error") or "网易云同步暂未更新", "warn")
        elif position is not None:
            self._set_chip(self.sync_chip, "网易云精确同步", "good")
        else:
            error = progress.get("error") or "等待网易云播放器"
            self._set_chip(self.sync_chip, error, "warn")

        lyric_model = state.get("lyric_model") or {}
        if isinstance(display, dict):
            if display.get("applying", display.get("pending")) or (display.get("pending") and not display.get("verified")):
                self._set_chip(self.device_chip, "正在更新设备显示", "muted")
                self._set_chip(self.device_state, "等待音响确认…", "muted")
            elif display.get("last_error"):
                self._set_chip(self.device_chip, "设备显示待重试", "warn")
                self._set_chip(self.device_state, display["last_error"], "warn")
            elif display.get("verified"):
                self._set_chip(self.device_chip, "音响已确认显示", "good")
                self._set_chip(self.device_state, "设备显示正常", "good")
            else:
                self._set_chip(self.device_chip, "等待显示确认", "muted")
                self._set_chip(self.device_state, "应用场景后显示设备确认结果", "muted")
        elif lyric_model.get("is_lyric_enabled"):
            self._set_chip(self.device_chip, "设备歌词已开启", "good")
            self._set_chip(self.device_state, "歌词模式运行中", "good")
        elif lyric_model.get("error"):
            self._set_chip(self.device_chip, "无法读取设备", "warn")
            self._set_chip(self.device_state, lyric_model["error"], "warn")
        else:
            self._set_chip(self.device_chip, "设备歌词未开启", "muted")
            self._set_chip(self.device_state, "可点击“重新开启歌词”", "muted")

    def _animate_progress(self):
        if not self._progress_sample or self.nav.currentRow() != 0 or self.isMinimized():
            return
        position, duration, playing, sampled = self._progress_sample
        if position is None or not duration:
            self.current_time.setText("--:--")
            self.progress.setValue(0)
            return
        elapsed = min(2.5, max(0.0, time.monotonic() - sampled)) if playing else 0.0
        position = min(float(duration), max(0.0, float(position) + elapsed))
        self.current_time.setText(format_seconds(position))
        self.progress.setValue(max(0, min(1000, int(position / float(duration) * 1000))))


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Halo PixelBar 控制台")
    window = SettingsWindow()
    window.show()
    bridge = StartupBridge(window)
    bridge.ready.connect(window._reconnect)

    def start_services():
        ensure_tempo_hub_running()
        ensure_netease_running()
        bridge.ready.emit()

    threading.Thread(target=start_services, name="tempo-startup", daemon=True).start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
