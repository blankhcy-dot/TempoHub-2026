"""Verify patch preservation and release contents without launching hardware."""

import argparse
import sys
import zlib
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import patch_temphub


def module_payloads(executable):
    data, toc = patch_temphub.read_pyz_bytes(patch_temphub.extract_embedded_pyz(executable))
    return {name: data[offset:offset + length] for name, (_, offset, length) in toc}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--patched", type=Path, required=True)
    parser.add_argument("--installer", type=Path, required=True)
    args = parser.parse_args()
    original = module_payloads(args.original)
    patched = module_payloads(args.patched)
    target = "app.utils.pixel_lyrics_util"
    assert patched[target + "_orig"] == original[target], "Original lyrics fallback changed"
    for name, payload in original.items():
        if name != target:
            assert patched[name] == payload, "Unexpected module modification: " + name
    payloads = sorted((ROOT / "payload").glob("*.cpython-39.pyc"))
    assert len(payloads) >= 3, "Missing display transport payload"
    for path in payloads:
        name = path.name.removesuffix(".cpython-39.pyc")
        expected = path.read_bytes()
        assert zlib.decompress(patched["app.utils." + name]) == expected[16:], "Stale patch payload: " + name
    source_archive, target_archive = CArchiveReader(str(args.original)), CArchiveReader(str(args.patched))
    for name in source_archive.toc:
        if name not in ("PYZ.pyz", "PYZ-00.pyz"):
            assert source_archive.extract(name) == target_archive.extract(name), "Resource changed: " + name
    installer = CArchiveReader(str(args.installer))
    entries = {name.replace("\\", "/"): name for name in installer.toc}
    for relative in ["ui/lyrics_settings.py"] + ["payload/" + path.name for path in payloads]:
        assert installer.extract(entries[relative]) == (ROOT / relative).read_bytes(), "Stale installer file: " + relative
    print(f"Verified {len(original)} original modules, original resources, {len(payloads)} patch payloads and installer contents.")


if __name__ == "__main__":
    main()
