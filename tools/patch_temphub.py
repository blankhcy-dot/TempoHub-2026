"""Patch EDIFIER TempoHub's bundled NetEase lyric adapter.

The original PyInstaller PYZ module is retained under a separate import name,
and the replacement module is installed at the original import path. The
bootloader prefix and every non-PYZ CArchive payload are copied unchanged.
"""

from __future__ import annotations

import argparse
import marshal
import struct
import zlib
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader
from PyInstaller.archive.writers import CArchiveWriter


PYZ_MAGIC = b"PYZ\0"
WRAPPER_MODULE = "app.utils.pixel_lyrics_util"
ORIGINAL_MODULE = "app.utils.pixel_lyrics_util_orig"


def read_pyz_bytes(data: bytes):
    if data[:4] != PYZ_MAGIC:
        raise ValueError("not a PyInstaller PYZ archive")
    toc_offset = struct.unpack("!i", data[8:12])[0]
    toc = marshal.loads(data[toc_offset:])
    return data, toc


def extract_embedded_pyz(exe: Path) -> bytes:
    reader = CArchiveReader(str(exe))
    for name in ("PYZ.pyz", "PYZ-00.pyz"):
        if name in reader.toc:
            return reader.extract(name)
    raise ValueError("embedded PyInstaller PYZ archive not found")


def write_pyz(path: Path, original: bytes, toc, replacement: bytes):
    entries = []
    payloads = []
    seen_target = False
    data_offset = 17

    for name, (typecode, offset, length) in toc:
        raw = original[offset : offset + length]
        if name == WRAPPER_MODULE:
            seen_target = True
            original_payload = raw
            entries.append((ORIGINAL_MODULE, (typecode, data_offset, len(original_payload))))
            payloads.append(original_payload)
            data_offset += len(original_payload)
            entries.append((name, (typecode, data_offset, len(replacement))))
            payloads.append(replacement)
            data_offset += len(replacement)
        else:
            entries.append((name, (typecode, data_offset, len(raw))))
            payloads.append(raw)
            data_offset += len(raw)

    if not seen_target:
        raise ValueError(f"PYZ module not found: {WRAPPER_MODULE}")

    toc_data = marshal.dumps(entries)
    header = bytearray(17)
    header[:4] = PYZ_MAGIC
    header[4:8] = bytes.fromhex("610d0d0a")
    struct.pack_into("!i", header, 8, data_offset)

    with path.open("wb") as fp:
        fp.write(header)
        for payload in payloads:
            fp.write(payload)
        fp.write(toc_data)

    with path.open("rb") as fp:
        rebuilt = fp.read()
    rebuilt_offset = struct.unpack("!i", rebuilt[8:12])[0]
    rebuilt_toc = marshal.loads(rebuilt[rebuilt_offset:])
    names = {item[0] for item in rebuilt_toc}
    if WRAPPER_MODULE not in names or ORIGINAL_MODULE not in names:
        raise ValueError("rebuilt PYZ is missing wrapper/original module entries")
    return len(rebuilt_toc)


def patch_archive(original_exe: Path, patched_pyz: Path, output_exe: Path):
    reader = CArchiveReader(str(original_exe))
    start = reader._start_offset
    end = reader._end_offset
    source = original_exe.read_bytes()
    if end != len(source):
        raise ValueError("unexpected overlay after the PyInstaller archive")

    raw_entries = []
    for name, entry in reader.toc.items():
        offset, compressed_length, data_length, compress, typecode = entry
        if name == "PYZ.pyz":
            payload = patched_pyz.read_bytes()
            raw_entries.append(
                (name, payload, 0, len(payload), "z")
            )
        else:
            payload = source[start + offset : start + offset + compressed_length]
            raw_entries.append((name, payload, compress, data_length, typecode))

    archive_path = output_exe.with_suffix(output_exe.suffix + ".pkg")
    with archive_path.open("wb") as fp:
        toc_rows = []
        for name, payload, compress, data_length, typecode in raw_entries:
            offset = fp.tell()
            fp.write(payload)
            toc_rows.append(
                (offset, len(payload), data_length, compress, typecode, name)
            )
        for option in reader.options:
            toc_rows.append((0, 0, 0, 0, "o", option))

        toc_offset = fp.tell()
        toc_data = CArchiveWriter._serialize_toc(toc_rows)
        fp.write(toc_data)
        archive_length = toc_offset + len(toc_data) + CArchiveWriter._COOKIE_LENGTH
        cookie = struct.pack(
            CArchiveWriter._COOKIE_FORMAT,
            CArchiveWriter._COOKIE_MAGIC_PATTERN,
            archive_length,
            toc_offset,
            len(toc_data),
            309,
            b"python39.dll",
        )
        fp.write(cookie)

    with output_exe.open("wb") as fp:
        fp.write(source[:start])
        with archive_path.open("rb") as archive:
            while True:
                chunk = archive.read(1024 * 1024)
                if not chunk:
                    break
                fp.write(chunk)
    archive_path.unlink()

    verify = CArchiveReader(str(output_exe))
    if "PYZ.pyz" not in verify.toc:
        raise ValueError("patched executable has no PYZ entry")
    return output_exe.stat().st_size


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument(
        "--pyz",
        type=Path,
        help="optional extracted PYZ.pyz; read from --exe when omitted",
    )
    parser.add_argument("--replacement", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--patched-pyz", required=True, type=Path)
    args = parser.parse_args()

    pyz_bytes = args.pyz.read_bytes() if args.pyz else extract_embedded_pyz(args.exe)
    original_pyz, toc = read_pyz_bytes(pyz_bytes)
    replacement = zlib.compress(args.replacement.read_bytes()[16:], 6)
    count = write_pyz(args.patched_pyz, original_pyz, toc, replacement)
    size = patch_archive(args.exe, args.patched_pyz, args.output)
    print(f"patched PYZ entries: {count}")
    print(f"patched executable: {args.output} ({size} bytes)")


if __name__ == "__main__":
    main()
