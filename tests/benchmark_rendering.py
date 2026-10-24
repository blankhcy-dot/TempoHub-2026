"""Compare the former pixel loops with the optimized conversion paths."""

import base64
import importlib.util
import json
import statistics
import timeit
from pathlib import Path

from PyQt6.QtGui import QColor, QImage
import lyrics_settings as ui


def run(output_dir=None):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("scene_benchmark", root / "src/app/utils/tempo_scene_engine.py")
    scene = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scene)
    source = QImage(256, 32, QImage.Format.Format_Grayscale8)
    source.fill(QColor("white"))

    def old_matrix():
        return [[1 if source.pixelColor(x, y).lightness() >= 96 else 0
                 for x in range(256)] for y in range(32)]

    packed = bytes([0xAA]) * 1024
    frames = [base64.b64encode(packed).decode(), base64.b64encode(packed[::-1][:-1] + b"\xff").decode()]
    preview = ui.MatrixPreview()
    index = [0]

    def old_preview():
        image = QImage(256, 32, QImage.Format.Format_Grayscale8)
        image.fill(QColor("black"))
        offset = 0
        for y in range(32):
            for x_byte in range(32):
                value = packed[offset]
                offset += 1
                for bit in range(8):
                    if value & (1 << (7 - bit)):
                        image.setPixelColor(x_byte * 8 + bit, y, QColor("white"))
        preview._set_image(image)

    def new_preview():
        index[0] ^= 1
        preview.set_frame(frames[index[0]])

    results = {}
    for name, old, new in (("matrix_conversion", old_matrix, lambda: scene.SceneEngine._image_to_matrix(source)),
                            ("preview_conversion", old_preview, new_preview)):
        before = statistics.median(timeit.repeat(old, number=100, repeat=3)) * 10
        after = statistics.median(timeit.repeat(new, number=100, repeat=3)) * 10
        results[name] = {"before_ms": round(before, 4), "after_ms": round(after, 4),
                         "speedup": round(before / after, 1)}
    print(json.dumps(results, indent=2))
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "benchmark.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
