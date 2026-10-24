"""Compile the patch with the same Python minor version as official TempoHub."""

import os
import py_compile
import subprocess
import sys
from pathlib import Path


def main():
    if sys.version_info[:2] != (3, 9):
        raise SystemExit("Payloads must be compiled with Python 3.9, not the build host's Python.")
    # Frozen set constants otherwise vary with the interpreter's hash seed,
    # causing identical sources to produce different packaged payload bytes.
    if os.environ.get("PYTHONHASHSEED") != "0":
        environment = dict(os.environ, PYTHONHASHSEED="0")
        subprocess.run([sys.executable, str(Path(__file__).resolve())], env=environment, check=True)
        return
    root = Path(__file__).resolve().parents[1]
    for name in ("pixel_lyrics_util", "tempo_device_display"):
        py_compile.compile(
            str(root / "src" / "app" / "utils" / (name + ".py")),
            cfile=str(root / "payload" / (name + ".cpython-39.pyc")),
            dfile="app/utils/" + name + ".py",
            doraise=True,
        )
        print("Compiled " + name)


if __name__ == "__main__":
    main()
