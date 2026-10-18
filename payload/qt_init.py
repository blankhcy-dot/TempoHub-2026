import os
import pkgutil


__path__ = pkgutil.extend_path(__path__, __name__)

_qt_bin = os.path.join(os.path.dirname(__file__), "Qt6", "bin")
_qt_core = os.path.join(_qt_bin, "Qt6Core.dll")
if os.path.isfile(_qt_core):
    os.environ["PATH"] = _qt_bin + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(_qt_bin)
