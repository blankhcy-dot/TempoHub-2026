"""Run regression tests with Python 3.9 and an installed TempoHub Qt runtime.

runtime39/python.exe tests/run_tests.py --qt-app "C:/Program Files (x86)/EDIFIER TempoHub"
An ordinary Python with PyQt6 installed also works without --qt-app.
"""

import argparse
import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--qt-app", type=Path)
parser.add_argument("--snapshots", type=Path)
parser.add_argument("--benchmark", action="store_true")
parser.add_argument("--audio-previews", type=Path)
parser.add_argument("--performance-previews", type=Path)
args = parser.parse_args()
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "ui")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
handles = []
if args.qt_app:
    internal = args.qt_app / "_internal"
    qt = internal / "PyQt6"
    handles = [os.add_dll_directory(str(internal)),
               os.add_dll_directory(str(qt / "Qt6" / "bin"))]
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(qt / "Qt6" / "plugins" / "platforms")
    # Official packages omit pure Python __init__.py files in _internal.
    package = types.ModuleType("PyQt6")
    package.__file__ = str(qt / "__init__.py")
    package.__path__ = [str(qt)]
    sys.modules["PyQt6"] = package

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFontDatabase
app = QApplication.instance() or QApplication([])
# Windows' offscreen platform does not discover the installed font families.
if os.name == "nt":
    for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "segoeuib.ttf",
                     "seguisb.ttf", "seguiemj.ttf", "consola.ttf"):
        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
import test_regressions
import test_device_display
test_regressions.SNAPSHOT_DIR = args.snapshots
result = unittest.TextTestRunner(verbosity=2).run(
    unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module)
                       for module in (test_regressions, test_device_display)))
if result.wasSuccessful() and args.benchmark:
    import benchmark_rendering
    benchmark_rendering.run(args.snapshots)
if result.wasSuccessful() and args.audio_previews:
    import preview_audio_styles
    preview_audio_styles.render(args.audio_previews)
if result.wasSuccessful() and args.performance_previews:
    import preview_performance_styles
    preview_performance_styles.render(args.performance_previews)
raise SystemExit(0 if result.wasSuccessful() else 1)
