import ast
import base64
import builtins
import concurrent.futures
import importlib.util
import http.client
import json
import math
import os
import sys
import tempfile
import threading
import time
import unittest
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PyQt6.QtGui import QColor, QImage, QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
import lyrics_settings as ui


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = None


def pump_until(predicate, timeout=4.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return
        time.sleep(0.002)
    raise AssertionError("Timed out waiting for Qt callback")


def load_runtime_functions(names, namespace):
    """Isolate storage/HTTP helpers without starting hardware collectors."""
    tree = ast.parse((ROOT / "src/app/utils/pixel_lyrics_util.py").read_text(encoding="utf-8"))
    selected = [node for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(ROOT / "src/app/utils/pixel_lyrics_util.py"), "exec"), namespace)
    return SimpleNamespace(**{name: namespace[name] for name in names})


class Handler(BaseHTTPRequestHandler):
    events = []
    delay = 0.0
    fail_settings = False
    post_gate = None
    started_requests = []
    confirm_display = True
    state = {"scene": "lyrics", "running": True, "song": "夜空中最亮的星",
             "artist": "逃跑计划 · 测试数据", "last_lyric": "每当我找不到存在的意义",
             "netease_progress": {"position": 43.0, "duration": 251.0},
             "is_playing": True, "lyric_model": {"is_lyric_enabled": True}}
    settings = {"scene": "lyrics", "sound_mode": 0, "line_offset_ms": 0}

    def log_message(self, *_):
        pass

    def send_json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def do_GET(self):
        time.sleep(self.delay)
        self.events.append(("GET", self.path))
        if self.path == "/error":
            self.send_json(500, {"error": "device unavailable"})
        elif self.path == "/api/settings":
            self.send_json(200, self.settings)
        elif self.path == "/api/state":
            self.send_json(200, self.state)
        elif self.path == "/api/eq/info":
            self.send_json(200, {"eq_index": 1})
        elif self.path == "/api/scene-frame":
            self.send_json(200, {"scene": self.settings["scene"],
                                 "audio_mode": self.settings.get("audio_mode", "bars"),
                                 "performance_mode": self.settings.get("performance_mode", "tiles"),
                                 "matrix": base64.b64encode(bytes(1024)).decode()})
        else:
            self.send_json(200, {"ok": True})

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        gate = self.post_gate
        self.started_requests.append(self.path)
        if gate is not None:
            gate.wait(timeout=3)
        time.sleep(self.delay)
        self.events.append(("POST", self.path, data))
        if self.path == "/api/settings":
            if self.fail_settings:
                self.send_json(500, {"error": "settings write failed"})
                return
            self.settings.update(data)
        self.send_json(200, {"settings": dict(self.settings), "applied": True,
                             "display": {"verified": self.confirm_display, "scene": self.settings["scene"]}})


class QtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.original_base = ui.API_BASE
        ui.API_BASE = "http://127.0.0.1:%d" % cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        ui.API_BASE = cls.original_base
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Handler.events = []
        Handler.delay = 0.0
        Handler.fail_settings = False
        Handler.post_gate = None
        Handler.started_requests = []
        Handler.confirm_display = True
        Handler.settings = {"scene": "lyrics", "sound_mode": 0, "line_offset_ms": 0}
        self.clients = []
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            # Fixture cleanup must not wait on an intentional failed save.
            window._allow_close = True
            window.close()
        for client in self.clients:
            client.close()
        QApplication.processEvents()

    def client(self):
        client = ui.ApiClient()
        self.clients.append(client)
        return client

    def window(self):
        window = ui.SettingsWindow()
        self.windows.append(window)
        window.show()
        pump_until(lambda: window._settings_loaded and window._connected)
        return window

    def test_window_has_unified_transparent_corners_and_real_controls(self):
        window = self.window()
        self.assertTrue(window.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertTrue(window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertEqual(len(window.resize_handles), 8)
        self.assertNotEqual(QApplication.focusWidget(), window.title_bar.close_button)
        pixmap = window.grab()
        image = pixmap.toImage()
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        scale = pixmap.devicePixelRatio()
        self.assertEqual(image.pixelColor(round(100 * scale), round(24 * scale)).alpha(), 255)

    def test_custom_maximize_restore_and_double_click(self):
        window = self.window()
        window.title_bar.maximize_button.click()
        QApplication.processEvents()
        self.assertTrue(window.isMaximized())
        self.assertEqual(window.window_shell.inset, 0)
        self.assertTrue(all(not handle.isVisible() for handle in window.resize_handles.values()))
        window.title_bar.maximize_button.click()
        QApplication.processEvents()
        self.assertFalse(window.isMaximized())
        self.assertEqual(window.window_shell.inset, 6)
        QTest.mouseDClick(window.title_bar, Qt.MouseButton.LeftButton, pos=QPoint(150, 20))
        self.assertTrue(window.isMaximized())

    def test_custom_minimize_button(self):
        window = self.window()
        window.title_bar.minimize_button.click()
        QApplication.processEvents()
        self.assertTrue(window.isMinimized())
        window.showNormal()

    def test_title_bar_drag_and_resize_fallback_respect_minimum_size(self):
        window = self.window()
        fake_handle = SimpleNamespace(startSystemMove=lambda: False, startSystemResize=lambda edges: False)

        def event(kind, x, y):
            return QMouseEvent(kind, QPointF(20, 20), QPointF(x, y),
                               Qt.MouseButton.LeftButton if kind == QEvent.Type.MouseButtonPress else Qt.MouseButton.NoButton,
                               Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)

        with patch.object(window, "windowHandle", return_value=fake_handle):
            origin = QPoint(window.pos())
            window.title_bar.mousePressEvent(event(QEvent.Type.MouseButtonPress, 300, 200))
            window.title_bar.mouseMoveEvent(event(QEvent.Type.MouseMove, 340, 225))
            self.assertEqual(window.pos(), origin + QPoint(40, 25))
            corner = window.resize_handles["bottom_right"]
            size = window.size()
            corner.mousePressEvent(event(QEvent.Type.MouseButtonPress, 500, 400))
            corner.mouseMoveEvent(event(QEvent.Type.MouseMove, 540, 430))
            self.assertEqual(window.width(), size.width() + 40)
            self.assertEqual(window.height(), size.height() + 30)
            corner.mouseMoveEvent(event(QEvent.Type.MouseMove, -10000, -10000))
            self.assertEqual(window.width(), window.minimumWidth())
            self.assertEqual(window.height(), window.minimumHeight())

    def test_custom_close_saves_and_remains_available_while_waiting(self):
        window = self.window()
        window.offset.setValue(275)
        window.title_bar.close_button.click()
        self.assertFalse(window.content_root.isEnabled())
        self.assertTrue(window.title_bar.close_button.isEnabled())
        pump_until(lambda: not window.isVisible())
        self.assertEqual(Handler.settings["line_offset_ms"], 275)

    def test_custom_close_allows_a_second_click_during_wait(self):
        window = self.window()
        with patch.object(window.api, "has_pending_writes", return_value=True):
            window.title_bar.close_button.click()
            self.assertTrue(window.isVisible())
            self.assertFalse(window.content_root.isEnabled())
            self.assertTrue(window.title_bar.close_button.isEnabled())
            window.title_bar.close_button.click()
            self.assertFalse(window.isVisible())

    def test_alt_f4_still_closes_the_frameless_window(self):
        window = self.window()
        window.activateWindow()
        window.setFocus()
        QApplication.processEvents()
        QTest.keyClick(window, Qt.Key.Key_F4, Qt.KeyboardModifier.AltModifier)
        pump_until(lambda: not window.isVisible())

    def test_all_eight_resize_directions_keep_opposite_edges_fixed(self):
        window = self.window()
        fake_handle = SimpleNamespace(startSystemResize=lambda edges: False)
        with patch.object(window, "windowHandle", return_value=fake_handle):
            for name, handle in window.resize_handles.items():
                window.setGeometry(100, 100, 1180, 760)
                before = window.geometry()
                dx = -30 if handle.edges & Qt.Edge.LeftEdge else 30 if handle.edges & Qt.Edge.RightEdge else 0
                dy = -20 if handle.edges & Qt.Edge.TopEdge else 20 if handle.edges & Qt.Edge.BottomEdge else 0
                handle.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(3, 3),
                    QPointF(300, 300), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier))
                handle.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, QPointF(3, 3),
                    QPointF(300 + dx, 300 + dy), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier))
                after = window.geometry()
                self.assertEqual(after.width(), before.width() + (30 if dx else 0), name)
                self.assertEqual(after.height(), before.height() + (20 if dy else 0), name)
                if handle.edges & Qt.Edge.LeftEdge:
                    self.assertEqual(after.right(), before.right(), name)
                if handle.edges & Qt.Edge.TopEdge:
                    self.assertEqual(after.bottom(), before.bottom(), name)

    def test_slow_http_keeps_gui_alive_and_deduplicates_reads(self):
        Handler.delay = 0.3
        client = self.client()
        completed, ticks = [], []
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: ticks.append(time.monotonic()))
        timer.start()
        for _ in range(30):
            client.get("/slow", lambda data, error: completed.append((data, error)))
        pump_until(lambda: completed)
        timer.stop()
        self.assertIsNone(completed[0][1])
        self.assertGreaterEqual(len(ticks), 12)
        self.assertEqual(Handler.events.count(("GET", "/slow")), 1)

    def test_writes_preserve_order_and_coalesce_adjacent_edits(self):
        Handler.delay = 0.04
        client = self.client()
        completed = []
        callback = lambda data, error: completed.append(error)
        client.post("/first", {}, callback)
        for index in range(20):
            client.post("/edit", {"value": index}, callback, coalesce="edit")
        client.post("/action", {}, callback)
        client.post("/edit", {"value": 99}, callback, coalesce="edit")
        pump_until(lambda: len(completed) == 4)
        posts = [event for event in Handler.events if event[0] == "POST"]
        self.assertEqual([p[1] for p in posts], ["/first", "/edit", "/action", "/edit"])
        self.assertEqual([posts[1][2]["value"], posts[3][2]["value"]], [19, 99])

    def test_notification_finishes_before_later_scene_change(self):
        window = self.window()
        Handler.delay = 0.04
        window._test_notification("微信", "测试消息")
        window.nav.setCurrentRow(1)
        pump_until(lambda: not window.api._writing and not window.api._writes)
        posts = [event for event in Handler.events if event[0] == "POST"]
        self.assertEqual([p[1] for p in posts],
                         ["/api/settings", "/api/notifications/test", "/api/settings"])
        self.assertEqual([posts[0][2]["scene"], posts[2][2]["scene"]], ["notifications", "audio"])

    def test_timeout_errors_and_close_cancel_callbacks(self):
        client = self.client()
        result = []
        Handler.delay = 0.25
        client.get("/timeout", lambda data, error: result.append(error), timeout=0.03)
        pump_until(lambda: result)
        self.assertIsNotNone(result[0])
        Handler.delay = 0
        client.get("/error", lambda data, error: result.append(error))
        pump_until(lambda: len(result) == 2)
        self.assertIn("device unavailable", str(result[1]))
        client.get("/cancel", lambda *_: self.fail("Callback fired after close"))
        client.close()
        QApplication.processEvents()

    def test_scene_switch_does_not_accept_stale_preview(self):
        window = self.window()
        pending = []
        window.api.get = lambda path, callback, **kw: pending.append(callback)
        window._suppress_scene_change = True
        window.nav.setCurrentRow(1)
        window._refresh_scene_preview()
        window.nav.setCurrentRow(2)
        before = window.notification_preview.pixmap().cacheKey()
        pending[0]({"scene": "audio", "matrix": base64.b64encode(b"\xff" * 1024).decode()}, None)
        self.assertEqual(before, window.notification_preview.pixmap().cacheKey())

    def test_disconnect_backoff_and_recovery(self):
        window = self.window()
        for _ in range(5):
            window._state_received(None, RuntimeError("offline"))
        self.assertEqual(window.timer.interval(), 8000)
        self.assertFalse(window._connected)
        window.feedback.setText("场景应用失败，请检查连接后重试")
        window.feedback.setToolTip("Connection refused")
        window._state_received(Handler.state, None)
        self.assertEqual(window.timer.interval(), 1000)
        self.assertTrue(window._connected)
        self.assertIn("连接已恢复", window.feedback.text())
        self.assertEqual(window.feedback.toolTip(), "")

    def test_pending_scene_is_preserved_when_opening_sound_page(self):
        window = self.window()
        Handler.delay = 0.08
        window.nav.setCurrentRow(1)
        window.audio_sensitivity.setValue(70)
        window.nav.setCurrentRow(4)
        self.assertEqual(window._selected_scene(), "audio")
        window._apply_scene_options(reapply_device=False)
        pump_until(lambda: not window.api._writing and not window.api._writes)
        self.assertEqual(Handler.settings["scene"], "audio")

    def test_restore_reply_does_not_override_a_newer_navigation(self):
        window = self.window()
        Handler.delay = 0.08
        window._restore_native()
        window.nav.setCurrentRow(1)
        pump_until(lambda: not window.api._writing and not window.api._writes)
        self.assertEqual(window.nav.currentRow(), 1)
        self.assertEqual(Handler.settings["scene"], "audio")

    def test_saved_settings_without_device_ack_are_not_display_success(self):
        window = self.window()
        Handler.confirm_display = False
        completed = []
        window._apply_scene_options(on_success=lambda: completed.append(True))
        pump_until(lambda: not window.api._writing and not window.api._writes)
        self.assertFalse(completed)
        self.assertIn("失败", window.feedback.text())
        self.assertIn("尚未确认", window.feedback.toolTip())

    def test_native_restore_without_device_ack_does_not_report_success(self):
        window = self.window()
        Handler.confirm_display = False
        window._restore_native()
        pump_until(lambda: not window.api._writing and not window.api._writes)
        self.assertIn("失败", window.feedback.text())

    def test_device_status_uses_confirmed_scene_instead_of_saved_scene(self):
        window = self.window()
        state = dict(Handler.state, scene="audio", running=False,
                     display={"connected": True, "verified": True, "scene": "performance"})
        window._state_received(state, None)
        self.assertIn("游戏性能", window.nav_state.text())
        self.assertIn("已连接", window.status.text())
        state["display"] = {"connected": True, "verified": False, "last_error": "传输超时"}
        window._state_received(state, None)
        self.assertIn("等待确认", window.nav_state.text())
        self.assertEqual(window.device_state.text(), "传输超时")

    def test_stale_or_failed_progress_is_not_reported_as_precise_sync(self):
        window = self.window()
        for progress in ({"position": 42.0, "duration": 200.0, "error": "timed out"},
                         {"position": 42.0, "duration": 200.0, "stale": True}):
            state = dict(Handler.state, netease_progress=progress)
            window._state_received(state, None)
            self.assertEqual(window.sync_chip.objectName(), "chipWarn")
            self.assertFalse(window._progress_sample[2])

    def test_small_window_and_all_pages_render(self):
        window = self.window()
        window._suppress_scene_change = True
        for width, height in ((1180, 760), (960, 620)):
            window.resize(width, height)
            for row in range(5):
                window.nav.setCurrentRow(row)
                QApplication.processEvents()
                scroll = window.pages.widget(row)
                self.assertLessEqual(scroll.widget().minimumSizeHint().width(), scroll.viewport().width())
                self.assertLessEqual(window.width(), width)
                if SNAPSHOT_DIR:
                    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
                    window.grab().save(str(SNAPSHOT_DIR / f"page-{row}-{width}.png"))

    def test_monochrome_preview_matches_wire_pixels(self):
        preview = ui.MatrixPreview()
        packed = bytes([0b10110001]) + bytes(1023)
        preview.set_frame(base64.b64encode(packed).decode())
        source = preview._source_pixmap.toImage()
        # _set_image scales the 256 x 32 source by exactly two.
        self.assertEqual([source.pixelColor(x * 2, 0).red() for x in range(8)],
                         [255, 0, 255, 255, 0, 0, 0, 255])
        key = preview.pixmap().cacheKey()
        preview.set_frame(base64.b64encode(packed).decode())
        self.assertEqual(key, preview.pixmap().cacheKey())

    def test_settings_switch_label_and_keyboard_toggle_once(self):
        switch = ui.SettingsSwitch("QQ")
        switch.resize(200, 38)
        changes = []
        switch.toggled.connect(changes.append)
        switch.show()
        try:
            QApplication.processEvents()
            QTest.mouseClick(switch, Qt.MouseButton.LeftButton, pos=QPoint(10, 19))
            self.assertTrue(switch.isChecked())
            QTest.keyClick(switch, Qt.Key.Key_Space)
            self.assertFalse(switch.isChecked())
            self.assertEqual(changes, [True, False])
        finally:
            switch.close()

    def test_new_audio_style_loads_description_without_sending_a_scene_change(self):
        Handler.settings["audio_mode"] = "particles"
        window = self.window()
        self.assertEqual(window.audio_mode.currentData(), "particles")
        self.assertIn("星点", window.audio_style_hint.text())
        self.assertEqual(window.audio_mode.count(), 9)
        self.assertFalse(any(event[0] == "POST" for event in Handler.events))

    def test_old_audio_style_frame_cannot_overwrite_a_new_selection(self):
        window = self.window()
        callbacks = []
        window._suppress_scene_change = True
        window.nav.setCurrentRow(1)
        window.api.get = lambda path, callback, **kw: callbacks.append(callback)
        window._refresh_scene_preview()
        before = window.audio_preview.pixmap().cacheKey()
        window.audio_mode.setCurrentIndex(window.audio_mode.findData("particles"))
        callbacks[0]({"scene": "audio", "audio_mode": "bars",
                      "matrix": base64.b64encode(b"\xff" * 1024).decode()}, None)
        self.assertEqual(window.audio_preview.pixmap().cacheKey(), before)

    def test_switch_signal_blocking_still_updates_its_visual_state(self):
        switch = ui.SettingsSwitch("QQ")
        switch.resize(200, 38)
        switch.show()
        try:
            QApplication.processEvents()
            previous = switch.blockSignals(True)
            switch.setChecked(True)
            switch.blockSignals(previous)
            QApplication.processEvents()
            pixmap = switch.grab()
            scale = pixmap.devicePixelRatio()
            color = pixmap.toImage().pixelColor(round(170 * scale), round(19 * scale))
            self.assertTrue(switch.isChecked())
            self.assertLess(color.red(), 60, "Checked switch is still painted in the off state")
            self.assertGreater(color.blue(), 200)
        finally:
            switch.close()

    def test_reconnect_refreshes_settings_without_changing_browsed_page(self):
        window = self.window()
        window.nav.setCurrentRow(4)
        Handler.settings.update(line_offset_ms=1200, notify_qq=False, audio_sensitivity=80)
        window._reconnect()
        pump_until(lambda: window.offset.value() == 1200)
        self.assertFalse(window.notify_qq.isChecked())
        self.assertEqual(window.audio_sensitivity.value(), 80)
        self.assertEqual(window.nav.currentRow(), 4)

    def test_delayed_settings_read_does_not_replace_newer_edits(self):
        window = self.window()
        callbacks = []
        window.api.get = lambda path, callback, **kw: callbacks.append(callback)
        window._load_settings()
        window.notify_qq.setChecked(False)
        callbacks[0]({"notify_qq": True, "line_offset_ms": 0}, None)
        self.assertFalse(window.notify_qq.isChecked())

    def test_close_flushes_pending_switch_and_offset_changes(self):
        window = self.window()
        window.notify_qq.setChecked(False)
        window.offset.setValue(375)
        window.close()
        pump_until(lambda: not window.isVisible())
        self.assertFalse(Handler.settings.get("notify_qq", True))
        self.assertEqual(Handler.settings["line_offset_ms"], 375)

    def test_close_waits_for_an_already_sending_save(self):
        window = self.window()
        Handler.delay = 0.12
        window.offset.setValue(625)
        window._apply_offset()
        window.close()
        pump_until(lambda: not window.isVisible())
        self.assertEqual(Handler.settings["line_offset_ms"], 625)

    def test_failed_close_save_keeps_window_open_and_allows_explicit_exit(self):
        window = self.window()
        Handler.fail_settings = True
        window.notify_qq.setChecked(False)
        window.close()
        pump_until(lambda: "保存失败，窗口已保留" in window.feedback.text())
        self.assertTrue(window.isVisible())
        self.assertTrue(window.centralWidget().isEnabled())
        window.close()
        self.assertFalse(window.isVisible())

    def test_failed_save_is_not_replaced_by_a_reconnect_read(self):
        window = self.window()
        Handler.fail_settings = True
        window.notify_qq.setChecked(False)
        window.close()
        pump_until(lambda: "保存失败，窗口已保留" in window.feedback.text())
        Handler.fail_settings = False
        window._reconnect()
        pump_until(lambda: "有操作未保存" in window.feedback.text())
        self.assertFalse(window.notify_qq.isChecked())
        window._apply_scene_options()
        pump_until(lambda: not window.api.has_pending_writes())
        self.assertFalse(Handler.settings["notify_qq"])

    def test_close_save_timeout_restores_controls_and_late_reply_does_not_close(self):
        window = self.window()
        Handler.delay = 0.18
        window.close_wait_timer.setInterval(30)
        window.offset.setValue(725)
        window.close()
        pump_until(lambda: "保存尚未完成" in window.feedback.text())
        self.assertTrue(window.isVisible())
        self.assertTrue(window.centralWidget().isEnabled())
        pump_until(lambda: not window.api.has_pending_writes())
        self.assertTrue(window.isVisible())
        window.close()
        self.assertFalse(window.isVisible())
        self.assertEqual(Handler.settings["line_offset_ms"], 725)

    def test_second_close_after_timeout_exits_with_request_still_pending(self):
        window = self.window()
        gate = threading.Event()
        Handler.post_gate = gate
        window.close_wait_timer.setInterval(30)
        window.offset.setValue(825)
        try:
            window.close()
            pump_until(lambda: "保存尚未完成" in window.feedback.text()
                       and "/api/settings" in Handler.started_requests)
            self.assertTrue(window.api.has_pending_writes())
            window.close()
            self.assertFalse(window.isVisible())
            gate.set()
            # Explicit exit may abort before acceptance; here the gate makes
            # server acceptance deterministic, even during high-DPI painting.
            pump_until(lambda: Handler.settings["line_offset_ms"] == 825)
        finally:
            gate.set()
            Handler.post_gate = None

    def test_long_sync_error_keeps_small_window_content_reachable(self):
        window = self.window()
        window.resize(960, 620)
        state = dict(Handler.state, netease_progress={"position": 10, "duration": 200,
                                                     "error": "connection error: " + "a" * 400})
        window._state_received(state, None)
        QApplication.processEvents()
        scroll = window.pages.widget(0)
        self.assertLessEqual(scroll.widget().minimumSizeHint().width(), scroll.viewport().width())
        self.assertEqual(window.sync_chip.toolTip(), state["netease_progress"]["error"])

    def test_unknown_eq_capability_is_not_reported_as_unsupported(self):
        window = self.window()
        window.api.get = lambda path, callback, **kw: callback({"eq_index": 14,
            "driver_ready": False, "custom_eq_probe": {"supported": None, "error": "设备未返回查询结果"}}, None)
        window._load_eq_capability()
        self.assertNotIn("不支持", window.sound_capability.text())
        self.assertEqual(window.sound_capability.objectName(), "chipWarn")


    def test_performance_style_load_and_metric_switches_do_not_save_on_load(self):
        Handler.settings.update(scene="performance", performance_mode="hud", perf_show_gpu=False)
        window = self.window()
        self.assertEqual(window.performance_mode.count(), 6)
        self.assertEqual(window.performance_mode.currentData(), "hud")
        self.assertFalse(window.performance_toggles["gpu"].isChecked())
        self.assertIn("切角", window.performance_style_hint.text())
        self.assertFalse(any(event[0] == "POST" for event in Handler.events))
        window.performance_toggles["cpu"].setChecked(False)
        payload = window._settings_payload()
        self.assertEqual(payload["performance_mode"], "hud")
        self.assertFalse(payload["perf_show_cpu"])
        self.assertFalse(payload["perf_show_gpu"])

    def test_old_performance_style_preview_is_rejected(self):
        Handler.settings.update(scene="performance", performance_mode="tiles")
        window = self.window()
        callbacks = []
        window.api.get = lambda path, callback, **kwargs: callbacks.append(callback)
        window._refresh_scene_preview()
        window.performance_preview.set_frame("")
        window.performance_mode.setCurrentIndex(window.performance_mode.findData("hud"))
        old_frame = base64.b64encode(bytes([255]) * 1024).decode()
        with patch.object(window.performance_preview, "set_frame") as set_frame:
            callbacks[0]({"scene": "performance", "performance_mode": "tiles", "matrix": old_frame}, None)
            set_frame.assert_not_called()


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "settings.json"
        self.ns = dict(json=json, os=os, time=time, _SETTINGS_PATH=str(self.path),
                       _DEFAULT_SETTINGS={"line_offset_ms": 0, "audio_sensitivity": 55,
                                          "sound_mode": 0, "scene": "lyrics", "audio_mode": "bars",
                                          "performance_mode": "tiles"},
                       _SETTINGS_LOCK=threading.RLock(), _SETTINGS_CACHE=None,
                       _SETTINGS_CACHE_PATH=None, _SETTINGS_STAMP=None, _SETTINGS_CHECK_AT=0.0,
                       AUDIO_MODES=tuple(style[0] for style in ui.AUDIO_STYLES),
                       PERFORMANCE_MODES=tuple(style[0] for style in ui.PERFORMANCE_STYLES),
                       _SCENE_ENGINE=None, _ACTIVE_MONITOR=None,
                       _display_snapshot=lambda: {"verified": False})
        self.helpers = load_runtime_functions({"_load_settings", "_save_settings", "_normalize_settings",
                                               "_apply_lyric_offset", "_shift_timeline"}, self.ns)
        self.ns["_run_device_job"] = lambda kind, **fields: self.ns["_apply_lyric_offset"](fields["offset_ms"])

    def tearDown(self):
        self.directory.cleanup()

    def test_parallel_writers_do_not_lose_changes(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: self.helpers._save_settings({f"writer_{i}": i}), range(24)))
        stored = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertTrue(all(stored[f"writer_{i}"] == i for i in range(24)))
        self.assertFalse(Path(str(self.path) + ".tmp").exists())

    def test_cached_reads_and_identical_saves_avoid_io(self):
        self.helpers._save_settings({"line_offset_ms": 150})
        with patch.object(builtins, "open", side_effect=AssertionError("unexpected disk read")):
            for _ in range(100):
                settings = self.helpers._load_settings()
                self.assertEqual(settings["line_offset_ms"], 150)
                settings["line_offset_ms"] = -1
            self.helpers._save_settings({"line_offset_ms": 150})

    def test_external_edits_and_corrupt_files_keep_last_good_settings(self):
        self.helpers._save_settings({"line_offset_ms": 150})
        self.path.write_text('{"line_offset_ms": 250}', encoding="utf-8")
        self.ns["_SETTINGS_CHECK_AT"] = 0
        self.assertEqual(self.helpers._load_settings()["line_offset_ms"], 250)
        self.path.write_text('{broken', encoding="utf-8")
        self.ns["_SETTINGS_CHECK_AT"] = 0
        self.assertEqual(self.helpers._load_settings()["line_offset_ms"], 250)

    def test_invalid_ranges_are_normalized(self):
        stored = self.helpers._save_settings({"line_offset_ms": 90000, "sound_mode": None,
                                               "audio_sensitivity": "bad", "scene": "unknown"})
        self.assertEqual(stored["line_offset_ms"], 5000)
        self.assertEqual(stored["sound_mode"], 0)
        self.assertEqual(stored["audio_sensitivity"], 55)
        self.assertEqual(stored["scene"], "lyrics")

    def test_all_audio_modes_persist_and_unknown_modes_fall_back(self):
        for mode, _, _ in ui.AUDIO_STYLES:
            self.assertEqual(self.helpers._save_settings({"audio_mode": mode})["audio_mode"], mode)
        self.assertEqual(self.helpers._save_settings({"audio_mode": "unknown"})["audio_mode"], "bars")

    def test_performance_style_persists_and_unknown_style_falls_back(self):
        for mode, _, _ in ui.PERFORMANCE_STYLES:
            stored = self.helpers._save_settings({"performance_mode": mode})
            self.assertEqual(stored["performance_mode"], mode)
        self.assertEqual(self.helpers._save_settings({"performance_mode": "invalid"})["performance_mode"], "tiles")

    def test_http_rejects_malformed_payloads_and_preserves_scene_on_offset_edit(self):
        requests = []
        self.ns.update(BaseHTTPRequestHandler=BaseHTTPRequestHandler,
                       _ACTIVE_MONITOR=None,
                       _apply_device_display=lambda *a, **kw: requests.append("display") or {"verified": True},
                       _log=lambda *a, **kw: None)
        handler = load_runtime_functions({"_LocalApiHandler"}, self.ns)._LocalApiHandler
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            for body, length, expected in ((b"[]", "2", 400), (b"x", "bad", 400),
                                           (b"", "-1", 413), (b"", "65537", 413)):
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                connection.request("POST", "/api/settings", body=body, headers={"Content-Length": length})
                response = connection.getresponse()
                self.assertEqual(response.status, expected)
                response.read()
                connection.close()
            self.helpers._save_settings({"scene": "audio", "engine": "custom"})
            for payload in ({"line_offset_ms": 125, "reapply_device": False},
                            {"scene": "audio", "reapply_device": True}):
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                connection.request("POST", "/api/settings", body=json.dumps(payload))
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                result = json.loads(response.read())
                self.assertEqual(result["settings"]["scene"], "audio")
                connection.close()
                if "line_offset_ms" in payload:
                    self.assertEqual(requests, [])
            self.assertEqual(requests, ["display"])
        finally:
            server.shutdown()
            server.server_close()

    def test_offset_api_rebuilds_from_original_timeline_in_both_directions(self):
        changes = []
        monitor = SimpleNamespace(_netease_base_timeline=[(10.0, "first"), (20.0, "second")],
                                  _locate_and_send_lyric=lambda: changes.append(True))
        self.ns.update(BaseHTTPRequestHandler=BaseHTTPRequestHandler, _ACTIVE_MONITOR=monitor)
        helpers = load_runtime_functions({"_LocalApiHandler", "_shift_timeline"}, self.ns)
        server = ThreadingHTTPServer(("127.0.0.1", 0), helpers._LocalApiHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            for offset, expected in ((500, 9.5), (-500, 10.5), (-500, 10.5)):
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                connection.request("POST", "/api/settings", body=json.dumps(
                    {"line_offset_ms": offset, "reapply_device": False}))
                response = connection.getresponse()
                self.assertEqual(response.status, 200, response.read())
                connection.close()
                self.assertEqual(monitor._current_timeline[0][0], expected)
                self.assertEqual(monitor._netease_base_timeline[0][0], 10.0)
            self.assertEqual(len(changes), 2)
        finally:
            server.shutdown()
            server.server_close()


class LyricsTests(unittest.TestCase):
    def test_positive_offset_advances_lyrics_on_fetch_and_setting_changes(self):
        offsets = {"line_offset_ms": 500}
        ns = dict(time=time, _normalize_text=lambda value: str(value or "").casefold(),
                  _netease_sample_matches=lambda *_: True,
                  _netease_progress_snapshot=lambda *_: {"title": "Song", "track_id": "1"},
                  _fetch_netease_lyric_by_id=lambda *_: ("lrc", {"duration": 30000, "name": "Song"}),
                  parse_lrc_to_timeline=lambda _: [(10.0, "first"), (20.0, "second")],
                  _load_settings=lambda: dict(offsets),
                  _log=lambda *a, **kw: None,
                  _original_fetch_sync=lambda *_: self.fail("Unexpected QQ fallback"))
        tree = ast.parse((ROOT / "src/app/utils/pixel_lyrics_util.py").read_text(encoding="utf-8"))
        names = {"_fetch_and_parse_lyric_sync", "_shift_timeline"}
        selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        exec(compile(ast.Module(body=selected, type_ignores=[]), "lyrics.py", "exec"), ns)
        for offset, expected in ((500, 9.5), (-500, 10.5), (0, 10.0)):
            offsets["line_offset_ms"] = offset
            monitor = SimpleNamespace(_netease_source_active=True)
            ns["_fetch_and_parse_lyric_sync"](monitor, "Song", "Artist", 30,
                                              {"title": "Song", "track_id": "1"})
            self.assertEqual(monitor._current_timeline[0][0], expected)
            self.assertEqual(monitor._netease_base_timeline[0][0], 10.0)

    def test_old_progress_is_flagged_stale_and_fresh_progress_is_bounded(self):
        ns = dict(time=time, _NETEASE_PROGRESS_LOCK=threading.Lock(),
                  _NETEASE_PROGRESS={"position": 99.5, "duration": 100.0,
                                     "updated": time.time() - 0.8, "error": None})
        helper = load_runtime_functions({"_netease_progress_snapshot"}, ns)._netease_progress_snapshot
        sample = helper(True)
        self.assertLessEqual(sample["position"], 100.0)
        ns["_NETEASE_PROGRESS"]["updated"] = time.time() - 5.0
        self.assertTrue(helper(True).get("stale"))


class RenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("scene_engine", ROOT / "src/app/utils/tempo_scene_engine.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_image_conversion_matches_reference(self):
        image = QImage(256, 32, QImage.Format.Format_Grayscale8)
        for y in range(32):
            for x in range(256):
                value = (x * 37 + y * 19) % 256
                image.setPixelColor(x, y, QColor(value, value, value))
        expected = [[int(image.pixelColor(x, y).lightness() >= 96) for x in range(256)] for y in range(32)]
        self.assertEqual(self.module.SceneEngine._image_to_matrix(image), expected)

    def performance_engine(self, mode):
        engine = self.module.SceneEngine.__new__(self.module.SceneEngine)
        engine._lock = threading.RLock()
        engine._settings = {"scene": "performance", "performance_mode": mode}
        state = {"fps": 144, "cpu": 38, "gpu": 76, "memory": 62,
                 "cpu_temp": 51, "gpu_temp": 67,
                 "history": {key: [20 + 70 * abs(math.sin(i * 0.2 + phase)) for i in range(60)]
                             for phase, key in enumerate(("fps", "cpu", "gpu", "memory"))}}
        engine.snapshot = lambda: {"performance": state}
        return engine, state

    def test_performance_layouts_are_distinct_and_handle_missing_metrics(self):
        self.assertEqual(tuple(style[0] for style in ui.PERFORMANCE_STYLES), self.module.PERFORMANCE_MODES)
        frames = []
        for mode in self.module.PERFORMANCE_MODES:
            engine, state = self.performance_engine(mode)
            matrix = engine._render_matrix("performance")
            self.assertEqual((len(matrix), len(matrix[0])), (32, 256))
            self.assertEqual(set(value for row in matrix for value in row), {0, 1})
            frames.append(bytes(value for row in matrix for value in row))
            state.update(fps=None, cpu=None, gpu=None, memory=None, history={})
            self.assertTrue(any(map(any, engine._render_matrix("performance"))))
        self.assertEqual(len(set(frames)), 6)

    def test_hidden_metrics_do_not_leak_into_any_performance_layout(self):
        for mode in self.module.PERFORMANCE_MODES:
            engine, state = self.performance_engine(mode)
            engine._settings.update(perf_show_cpu=False, perf_show_gpu=False, perf_show_memory=False)
            before = engine._render_matrix("performance")
            state.update(cpu=100, gpu=100, memory=100, cpu_temp=99, gpu_temp=99)
            self.assertEqual(before, engine._render_matrix("performance"))
            engine._settings["perf_show_fps"] = False
            empty = engine._render_matrix("performance")
            state["fps"] = 999
            self.assertEqual(empty, engine._render_matrix("performance"))

    def audio_engine(self, mode):
        engine = self.module.SceneEngine.__new__(self.module.SceneEngine)
        engine._lock = threading.RLock()
        engine._audio_visual = None
        engine._settings = {"scene": "audio", "audio_mode": mode, "audio_sensitivity": 55}
        signal = {"levels": [0.2 + 0.7 * abs(math.sin(i * 0.37)) for i in range(32)],
                  "wave": [math.sin(i * 0.18) * 0.7 for i in range(128)],
                  "peak_db": -5.0, "rms_db": -13.0, "error": None}
        engine.snapshot = lambda: {"audio": signal}
        return engine, signal

    def test_audio_style_registry_and_monochrome_frames(self):
        self.assertEqual(tuple(style[0] for style in ui.AUDIO_STYLES), self.module.AUDIO_MODES)
        frames = []
        for mode in self.module.AUDIO_MODES:
            engine, signal = self.audio_engine(mode)
            for frame in range(40):
                with patch.object(self.module.time, "monotonic", return_value=1000 + frame * 0.1):
                    matrix = engine._render_matrix("audio")
            self.assertEqual(len(matrix), 32, mode)
            self.assertTrue(all(len(row) == 256 and set(row) <= {0, 1} for row in matrix), mode)
            self.assertGreater(sum(map(sum, matrix)), 0, mode)
            frames.append(bytes(value for row in matrix for value in row))
        self.assertEqual(len(set(frames)), len(self.module.AUDIO_MODES))

    def test_mirror_is_symmetric_in_both_axes(self):
        engine, _ = self.audio_engine("mirror")
        matrix = engine._render_matrix("audio")
        self.assertEqual(matrix, list(reversed(matrix)))
        self.assertTrue(all(row == list(reversed(row)) for row in matrix))

    def test_waterfall_history_is_bounded_and_signal_release_is_time_based(self):
        engine, _ = self.audio_engine("waterfall")
        for frame in range(200):
            with patch.object(self.module.time, "monotonic", return_value=1000 + frame * 0.1):
                visual = engine._audio_animation("waterfall", [0.5] * 32)
        self.assertEqual(len(visual["history"]), 32)
        results = []
        for step in (0.02, 0.1):
            engine, _ = self.audio_engine("bars")
            with patch.object(self.module.time, "monotonic", return_value=0):
                engine._audio_animation("bars", [1.0] * 32)
            for index in range(1, round(1 / step) + 1):
                with patch.object(self.module.time, "monotonic", return_value=index * step):
                    visual = engine._audio_animation("bars", [0.0] * 32)
            results.append(visual["levels"][0])
        self.assertAlmostEqual(results[0], results[1], places=10)

    def test_full_scale_vu_is_not_treated_as_silence(self):
        engine, signal = self.audio_engine("vu")
        signal.update(peak_db=0.0, rms_db=0.0)
        full = engine._render_matrix("audio")
        signal.update(peak_db=-80.0, rms_db=-80.0)
        silent = engine._render_matrix("audio")
        self.assertGreater(sum(map(sum, full)), sum(map(sum, silent)) + 1000)

    def test_disabled_notifications_do_not_replace_enabled_alerts(self):
        engine = self.module.SceneEngine.__new__(self.module.SceneEngine)
        engine._lock = threading.RLock()
        engine._settings = {"notify_wechat": True, "notify_qq": False, "notify_qqmail": False}
        engine._alert = None
        engine._set_alert("微信", "enabled")
        engine._set_alert("QQ", "disabled")
        self.assertEqual(engine._alert["app"], "微信")
        engine._set_alert("QQ邮箱", "disabled mail")
        self.assertEqual(engine._alert["app"], "微信")
        engine._settings["notify_qq"] = True
        engine._set_alert("QQ", "enabled QQ")
        self.assertEqual(engine._alert["text"], "enabled QQ")
        engine._settings["notify_qq"] = False
        engine.trigger_notification("QQ", "explicit local test")
        self.assertEqual(engine._alert["text"], "explicit local test")

    def test_disabling_notifications_clears_existing_passive_alert(self):
        engine = self.module.SceneEngine.__new__(self.module.SceneEngine)
        engine._lock = threading.RLock()
        engine._configure_lock = threading.RLock()
        engine._render_lock = threading.Lock()
        engine._render_cache = None
        engine._settings = {"scene": "notifications", "notify_qq": True}
        engine._fps_thread = None
        engine._fps_status = "未启用"
        engine._alert = None
        engine._set_alert("QQ", "message")
        engine.configure({"scene": "notifications", "notify_qq": False})
        self.assertIsNone(engine._alert)

    def test_multiple_qq_windows_do_not_repeat_unchanged_unread_titles(self):
        engine = self.module.SceneEngine.__new__(self.module.SceneEngine)
        engine._window_baseline = {}
        engine._last_window_alert = 0.0
        engine._settings = {"notify_qq": True}
        alerts = []
        engine._set_alert = lambda app, text: alerts.append((app, text)) or True
        windows = [(101, 50, "QQ"), (102, 50, "(1) QQ")]
        lookup = lambda pid: "qq.exe"
        engine._check_window_notifications(windows, lookup)
        for _ in range(5):
            engine._last_window_alert = 0
            engine._check_window_notifications(windows, lookup)
        self.assertEqual(alerts, [])
        engine._check_window_notifications([(101, 50, "QQ"), (102, 50, "(2) QQ")], lookup)
        self.assertEqual(len(alerts), 1)
        engine._check_window_notifications([(101, 50, "QQ")], lookup)
        self.assertEqual(len(engine._window_baseline), 1)

    def test_audio_stream_is_closed_when_stop_or_start_raises(self):
        engine = self.module.SceneEngine.__new__(self.module.SceneEngine)
        engine._lock = threading.RLock()
        engine._audio_capture_stop = threading.Event()
        engine._audio_capture_thread = None
        closed = []

        def fail():
            raise RuntimeError("device unplugged")

        stream = SimpleNamespace(stop=fail, close=lambda: closed.append(True))
        engine._audio_stream = stream
        engine._stop_audio_stream()
        self.assertEqual(closed, [True])
        self.assertIsNone(engine._audio_stream)
        closed.clear()
        stream.start = fail
        engine.app_dir = ROOT
        engine.log = lambda *a, **kw: None
        with patch.dict(sys.modules, {"numpy": SimpleNamespace(),
                "soundcard": SimpleNamespace(all_microphones=lambda **kw: []),
                "_sounddevice": SimpleNamespace(PaWasapi_UpdateDeviceList=lambda: None,
                                                 PaWasapi_IsLoopback=lambda _: True),
                "sounddevice": SimpleNamespace(query_devices=lambda: [
                    {"max_input_channels": 2, "default_samplerate": 48000}],
                    InputStream=lambda **kw: stream)}):
            engine._ensure_audio_stream()
        self.assertEqual(closed, [True])
        self.assertIn("device unplugged", engine._audio_error)

    def test_fps_snapshot_is_thread_safe_and_clears_stale_values(self):
        engine = self.module.SceneEngine.__new__(self.module.SceneEngine)
        engine._lock = threading.RLock()
        engine._fps_rows = {"game.exe": deque(maxlen=180)}
        engine._metrics = {"fps": 144.0}
        engine._history = {"fps": deque(maxlen=60)}
        stop = threading.Event()

        def writer():
            while not stop.is_set():
                with engine._lock:
                    engine._fps_rows.setdefault("game.exe", deque(maxlen=180)).append((time.monotonic(), 10.0))

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        try:
            pump_until(lambda: len(engine._fps_rows["game.exe"]) >= 4)
            for _ in range(500):
                engine._update_fps_from_rows()
            self.assertEqual(engine._metrics["fps"], 100.0)
        finally:
            stop.set()
            thread.join(timeout=1)
        with engine._lock:
            engine._fps_rows["game.exe"] = deque([(time.monotonic() - 30, 10.0)])
        engine._update_fps_from_rows()
        self.assertIsNone(engine._metrics["fps"])
        self.assertEqual(engine._fps_rows, {})
