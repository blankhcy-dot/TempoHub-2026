"""Render the six device layouts using explicitly synthetic telemetry."""
import importlib.util
import math
import threading
from pathlib import Path

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter
import lyrics_settings as ui


def render(output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parents[1] / "src/app/utils/tempo_scene_engine.py"
    spec = importlib.util.spec_from_file_location("performance_preview_engine", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = module.SceneEngine.__new__(module.SceneEngine)
    engine._lock = threading.RLock()
    state = {"fps": 144, "cpu": 38, "gpu": 76, "memory": 62, "gpu_temp": 67, "cpu_temp": 51,
             "history": {key: [20 + 70 * abs(math.sin(i * 0.2 + phase)) for i in range(60)]
                         for phase, key in enumerate(("fps", "cpu", "gpu", "memory"))}}
    engine.snapshot = lambda: {"performance": state}
    board = QImage(1060, 808, QImage.Format.Format_RGB32)
    board.fill(QColor("#F5F5F7"))
    painter = QPainter(board)
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(23)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#20242C"))
    painter.drawText(22, 33, "电脑性能 · 六种屏幕布局")
    font.setPixelSize(12)
    font.setBold(False)
    painter.setFont(font)
    painter.drawText(22, 55, "示例数据 · 设备原生 256 × 32 点阵")
    for index, (key, name, description) in enumerate(ui.PERFORMANCE_STYLES):
        engine._settings = {"scene": "performance", "performance_mode": key}
        matrix = engine._render_matrix("performance")
        pixels = bytes(value * 255 for row in matrix for value in row)
        frame = QImage(pixels, 256, 32, 256, QImage.Format.Format_Grayscale8).copy()
        frame.save(str(output_dir / (key + ".png")))
        top = 80 + index * 120
        font.setPixelSize(17)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(22, top + 24, name)
        font.setPixelSize(12)
        font.setBold(False)
        painter.setFont(font)
        painter.drawText(QRectF(22, top + 34, 210, 60), Qt.TextFlag.TextWordWrap, description)
        painter.drawImage(QRectF(268, top, 768, 96), frame)
    painter.end()
    board.save(str(output_dir / "performance-styles.png"))
    print("Performance previews: " + str(output_dir / "performance-styles.png"))
