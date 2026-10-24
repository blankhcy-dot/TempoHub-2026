from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import winreg
import zipfile
import zlib
from pathlib import Path


APP_NAME = "EDIFIER TempoHub"
PROJECT_DIR = Path(__file__).resolve().parent


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", PROJECT_DIR))
    return base / relative


def find_tempo_hub(explicit: Path | None = None) -> Path:
    if explicit:
        candidate = explicit / "EDIFIER TempoHub.exe" if explicit.is_dir() else explicit
        if candidate.is_file():
            return candidate
        raise FileNotFoundError(f"TempoHub executable not found: {candidate}")

    candidates = []
    for root_name in ("ProgramFiles(x86)", "ProgramFiles"):
        root = os.environ.get(root_name)
        if root:
            candidates.append(Path(root) / APP_NAME / "EDIFIER TempoHub.exe")

    registry_roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    for hive, key_path in registry_roots:
        try:
            with winreg.OpenKey(hive, key_path) as key:
                for index in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        subkey_name = winreg.EnumKey(key, index)
                        with winreg.OpenKey(key, subkey_name) as subkey:
                            display_name = str(
                                winreg.QueryValueEx(subkey, "DisplayName")[0]
                            )
                            if "tempo" not in display_name.casefold():
                                continue
                            try:
                                location = Path(
                                    str(winreg.QueryValueEx(subkey, "InstallLocation")[0])
                                )
                                candidates.append(location / "EDIFIER TempoHub.exe")
                            except OSError:
                                pass
                            try:
                                icon = str(
                                    winreg.QueryValueEx(subkey, "DisplayIcon")[0]
                                ).strip('"').split(",")[0]
                                candidates.append(Path(icon))
                            except OSError:
                                pass
                    except OSError:
                        continue
        except OSError:
            continue

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "未找到官方 EDIFIER TempoHub。请先安装官方客户端，"
        "或使用 --app-dir 指定安装目录。"
    )


def stop_tempo_hub() -> None:
    subprocess.run(
        ["taskkill", "/IM", "EDIFIER TempoHub.exe", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def ensure_runtime(target: Path) -> None:
    runtime_source = resource_path("runtime39")
    if not runtime_source.is_dir():
        archive = Path(tempfile.gettempdir()) / "python-3.9.13-embed-amd64.zip"
        if not archive.is_file():
            url = "https://www.python.org/ftp/python/3.9.13/python-3.9.13-embed-amd64.zip"
            print("正在下载 Python 3.9 运行库…")
            urllib.request.urlretrieve(url, archive)
        with zipfile.ZipFile(archive) as package:
            package.extractall(runtime_source)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(runtime_source, target)


def copy_qt_runtime(source_internal: Path, target_app: Path) -> None:
    source_qt = source_internal / "PyQt6"
    if not source_qt.is_dir():
        raise FileNotFoundError(
            "官方 TempoHub 中未找到 PyQt6，无法创建设置面板。"
        )
    target_qt = target_app / "PyQt6"
    if target_qt.exists():
        shutil.rmtree(target_qt)
    shutil.copytree(source_qt, target_qt)
    shutil.copy2(
        resource_path("payload") / "qt_init.py",
        target_qt / "__init__.py",
    )


def create_internal_junction(target_app: Path, source_internal: Path) -> None:
    link = target_app / "_internal"
    if link.exists():
        if link.resolve() == source_internal.resolve():
            return
        raise RuntimeError(
            f"{link} 已存在且不是指向官方 TempoHub 的目录。"
            "请手动检查后删除该临时目录。"
        )
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            (
                "New-Item -ItemType Junction -Path "
                f"'{{0}}' -Target '{{1}}' | Out-Null"
            ).format(str(link), str(source_internal)),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not link.exists():
        raise RuntimeError(
            "创建 _internal 目录连接失败：" + (result.stderr or result.stdout)
        )


def patch_executable(original_exe: Path, target_exe: Path, replacement_pyc: Path) -> None:
    tools_dir = resource_path("tools")
    sys.path.insert(0, str(tools_dir))
    import patch_temphub

    pyz_bytes = patch_temphub.extract_embedded_pyz(original_exe)
    original_pyz, toc = patch_temphub.read_pyz_bytes(pyz_bytes)
    replacement = zlib.compress(replacement_pyc.read_bytes()[16:], 6)
    extra_modules = {}
    for module_path in replacement_pyc.parent.glob("*.cpython-39.pyc"):
        if module_path == replacement_pyc:
            continue
        module_name = f"app.utils.{module_path.name.split('.cpython-39.pyc')[0]}"
        extra_modules[module_name] = zlib.compress(
            module_path.read_bytes()[16:],
            6,
        )
    with tempfile.TemporaryDirectory(prefix="tempo-patch-") as temp_dir:
        temp_pyz = Path(temp_dir) / "PYZ-patched.pyz"
        patch_temphub.write_pyz(
            temp_pyz,
            original_pyz,
            toc,
            replacement,
            extra_modules,
        )
        patch_temphub.patch_archive(original_exe, temp_pyz, target_exe)


def install_shortcuts(app_dir: Path) -> None:
    script = resource_path("scripts") / "create_shortcuts.ps1"
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-AppDir",
            str(app_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install the NetEase lyric bridge for EDIFIER TempoHub."
    )
    parser.add_argument("--app-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--no-shortcuts", action="store_true")
    args = parser.parse_args()

    original_exe = find_tempo_hub(args.app_dir)
    source_internal = original_exe.parent / "_internal"
    if not source_internal.is_dir():
        raise FileNotFoundError(f"缺少官方资源目录：{source_internal}")
    if not (source_internal / "python39.dll").is_file():
        raise RuntimeError(
            "当前 TempoHub 不是受支持的 Python 3.9 版本。"
            "请使用 README 中列出的官方版本。"
        )

    output = (
        args.output_dir
        or Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
        / "TempoHubNetEase"
    )
    output.mkdir(parents=True, exist_ok=True)
    print(f"官方程序：{original_exe}")
    print(f"安装位置：{output}")

    stop_tempo_hub()
    target_exe = output / "EDIFIER TempoHub.exe"
    patch_executable(
        original_exe,
        target_exe,
        resource_path("payload") / "pixel_lyrics_util.cpython-39.pyc",
    )
    create_internal_junction(output, source_internal)

    ensure_runtime(output / "runtime")
    copy_qt_runtime(source_internal, output)
    shutil.copy2(resource_path("ui") / "lyrics_settings.py", output / "lyrics_settings.py")
    shutil.copy2(
        resource_path("scripts") / "launch_netease_lyrics.ps1",
        output / "launch_netease_lyrics.ps1",
    )
    shutil.copy2(
        resource_path("scripts") / "uninstall.ps1",
        output / "uninstall.ps1",
    )
    (output / ".tempo-nexe-install").write_text(
        str(original_exe),
        encoding="utf-8",
    )

    if not args.no_shortcuts:
        install_shortcuts(output)

    print("安装完成。")
    print("请通过桌面快捷方式“EDIFIER TempoHub - 网易云歌词”启动。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"安装失败：{error}", file=sys.stderr)
        input("按 Enter 退出…")
        raise SystemExit(1)
