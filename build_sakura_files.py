"""打包 SakuraTools 为可安装的 zip。

仓库根目录就是插件本体（插件市场直接抓仓库源码），本脚本把与插件运行相关的文件
收进 zip 里的一层目录，供 Sakura 的“从 ZIP 安装”使用。

用法：
    python build_sakura_files.py

产物：sakuratools.files-<version>.zip
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

# Windows 控制台默认不是 UTF-8，print 中文会抛 UnicodeEncodeError。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass

HERE = Path(__file__).resolve().parent
PACKAGE_DIR_NAME = "sakuratools.files"
INCLUDE_FILES = ("plugin.yaml", "plugin.py", "selftest.py", "README.md", "LICENSE")
INCLUDE_DIRS = ("files_core",)
EXCLUDE_DIRS = {"__pycache__", ".selftest-tmp"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".zip"}


def version() -> str:
    text = (HERE / "plugin.yaml").read_text(encoding="utf-8")
    match = re.search(r"^version:\s*(\S+)\s*$", text, re.M)
    return match.group(1) if match else "0.0.0"


def iter_files() -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    for name in INCLUDE_FILES:
        path = HERE / name
        if path.is_file():
            files.append((path, name))
    for name in INCLUDE_DIRS:
        root = HERE / name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            relative_parts = path.relative_to(HERE).parts
            if any(part in EXCLUDE_DIRS for part in relative_parts):
                continue
            if not path.is_file() or path.suffix.casefold() in EXCLUDE_SUFFIXES:
                continue
            files.append((path, Path(*relative_parts).as_posix()))
    return files


def main() -> int:
    if not (HERE / "plugin.yaml").is_file():
        raise SystemExit("找不到 plugin.yaml")
    target = HERE / f"{PACKAGE_DIR_NAME}-{version()}.zip"
    files = iter_files()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, relative in files:
            archive.write(path, arcname=f"{PACKAGE_DIR_NAME}/{relative}")
    print(f"打包完成：{target}")
    print(f"文件数：{len(files)}，体积：{target.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
