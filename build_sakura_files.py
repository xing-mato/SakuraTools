"""打包 SakuraTools 插件为可安装的 zip。

用法（在本目录下）：
    D:\\AI\\sakura-exe\\Sakura\\python\\python.exe build_sakura_files.py

产物：本目录下的 sakuratools.files-<version>.zip（内含单层 sakuratools.files/ 目录），
可直接在 Sakura 的 设置 → 插件 → 从 ZIP 安装。
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "sakuratools.files"
EXCLUDE_DIRS = {"__pycache__", ".selftest-tmp", ".git", ".idea", ".vscode"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".zip"}


def version() -> str:
    text = (SOURCE / "plugin.yaml").read_text(encoding="utf-8")
    match = re.search(r"^version:\s*(\S+)\s*$", text, re.M)
    return match.group(1) if match else "0.0.0"


def iter_files() -> list[Path]:
    files: list[Path] = []
    for path in sorted(SOURCE.rglob("*")):
        if any(part in EXCLUDE_DIRS for part in path.relative_to(SOURCE).parts):
            continue
        if not path.is_file() or path.suffix.casefold() in EXCLUDE_SUFFIXES:
            continue
        files.append(path)
    return files


def main() -> int:
    if not (SOURCE / "plugin.yaml").is_file():
        raise SystemExit(f"找不到插件目录：{SOURCE}")
    target = HERE / f"{SOURCE.name}-{version()}.zip"
    files = iter_files()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(SOURCE).as_posix()
            archive.write(path, arcname=f"{SOURCE.name}/{relative}")
    print(f"打包完成：{target}")
    print(f"文件数：{len(files)}，体积：{target.stat().st_size // 1024} KB")
    with zipfile.ZipFile(target) as archive:
        print("条目：")
        for name in archive.namelist():
            print("  " + name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
