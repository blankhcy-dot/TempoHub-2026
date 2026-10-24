"""Render a deterministic audio-demo contact sheet and measure uncached frames."""

import importlib.util
import json
import math
import statistics
import timeit
from pathlib import Path
from unittest.mock import patch
import threading

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen
import lyrics_settings as ui


def render(output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(exist_ok=True)
    path = Path(__file__).resolve().parents[1] / "src/app/utils/tempo_scene_engine.py"
    spec = importlib.util.spec_from_file_location("audio_preview_engine", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engines, signals = {}, {}
    for mode, _, _ in ui.AUDIO_STYLES:
        engine = module.SceneEngine.__new__(module.SceneEngine)
        engine._lock = threading.RLock()
        engine._audio_visual = None
        engine._settings = {"scene": "audio", "audio_mode": mode, "audio_sensitivity": 55}
        signal = {"levels": [0.0] * 32, "wave": [0.0] * 128, "error": None}
        engine.snapshot = lambda signal=signal: {"audio": signal}
        engines[mode], signals[mode] = engine, signal

    styles = ui.AUDIO_STYLES[3:]
    for frame in range(80):
        elapsed = frame / 10
        beat = max(0.0, math.sin(elapsed * math.tau * 1.4)) ** 7
        signal_levels = [min(0.98, 0.12 + 0.42 * (1 + math.sin(i * 0.37 - elapsed * 1.7)) / 2
                             + beat * 0.52 * math.exp(-i / 10)
                             + 0.23 * math.sin(i * 0.73 + elapsed * 0.9) ** 2) for i in range(32)]
        for signal in signals.values():
            signal.update(levels=signal_levels,
                          wave=[math.sin(i * 0.18 + elapsed * 6) * (0.3 + beat * 0.6) for i in range(128)],
                          peak_db=-12 + beat * 11, rms_db=-20 + beat * 12)
        images = {}
        with patch.object(module.time, "monotonic", return_value=10000 + elapsed):
            for mode, engine in engines.items():
                matrix = engine._render_matrix("audio")
                data = bytes(value * 255 for row in matrix for value in row)
                images[mode] = QImage(data, 256, 32, 256, QImage.Format.Format_Grayscale8).copy()
        if frame < 32:
            continue
        board = QImage(1140, 514, QImage.Format.Format_RGB32)
        board.fill(QColor("#F5F5F7"))
        painter = QPainter(board)
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(23)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#20242C"))
        painter.drawText(18, 32, "6 种新频谱样式")
        font.setPixelSize(12)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor("#737B88"))
        painter.drawText(18, 54, "256 × 32 点阵  ·  模拟音频演示")
        for index, (mode, name, description) in enumerate(styles):
            x, y = 18 + (index % 2) * 560, 72 + (index // 2) * 146
            painter.setPen(QPen(QColor("#DFE4ED"), 1))
            painter.setBrush(QColor("white"))
            painter.drawRoundedRect(QRectF(x, y, 544, 132), 14, 14)
            font.setPixelSize(14)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#006FEA"))
            painter.drawText(x + 16, y + 23, name)
            font.setPixelSize(11)
            font.setBold(False)
            painter.setFont(font)
            painter.setPen(QColor("#737B88"))
            painter.drawText(x + 16, y + 41, description)
            painter.drawImage(QRectF(x + 16, y + 52, 512, 64), images[mode])
        painter.end()
        board.save(str(frames_dir / f"frame-{frame - 32:03d}.png"))
        if frame == 56:
            board.save(str(output_dir / "audio-styles.png"))
            for mode, image in images.items():
                image.scaled(1024, 128, Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.FastTransformation).save(str(output_dir / f"{mode}.png"))

    benchmarks = {}
    for mode, engine in engines.items():
        milliseconds = statistics.median(timeit.repeat(lambda: engine._render_matrix("audio"),
                                                      number=100, repeat=3)) * 10
        benchmarks[mode] = round(milliseconds, 3)
    (output_dir / "render-ms.json").write_text(json.dumps(benchmarks, indent=2), encoding="utf-8")
    print("Uncached render milliseconds:", json.dumps(benchmarks))
