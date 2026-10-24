"""插件配置：访问范围、结果条数上限、权限开关，以及设置页描述。"""

from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

SCOPES: dict[str, str] = {
    "home": "用户目录",
    "desktop": "桌面",
    "documents": "文档",
    "downloads": "下载",
    "pictures": "图片",
    "drives": "全部磁盘",
    "custom": "自定义目录",
}

SCOPE_OPTIONS = [{"label": label, "value": key} for key, label in SCOPES.items()]

LIMIT_MODES: dict[str, str] = {
    "custom": "自定义条数",
    "unlimited": "不限（有风险）",
}

LIMIT_OPTIONS = [{"label": label, "value": key} for key, label in LIMIT_MODES.items()]

PERMISSIONS: dict[str, str] = {
    "read_only": "只读",
    "full": "完全权限",
}

PERMISSION_OPTIONS = [{"label": label, "value": key} for key, label in PERMISSIONS.items()]

DEFAULTS: dict[str, Any] = {
    "scope": "home",
    "custom_roots": "",
    "file_limit_mode": "custom",
    "max_files": 50,
    "permission": "read_only",
}

MIN_FILES = 1
MAX_FILES = 500
DEFAULT_MAX_FILES = 50

# 用户选“不限”后仍然存在的结果硬顶，避免一次调用把进程拖死。
HARD_RESULT_CAP = 10000

# 单文件读取上限（不暴露在界面上）：防止误读超大文件把上下文撑爆。
MAX_FILE_BYTES = 48 * 1024 * 1024
# 单次返回字符硬顶（不暴露在界面上）。
MAX_RETURN_CHARS = 20000


@dataclass(frozen=True)
class FileConfig:
    roots: tuple[Path, ...]
    scope: str
    max_files: int | None
    permission: str
    notes: tuple[str, ...] = ()
    custom_roots: str = ""

    @property
    def read_only(self) -> bool:
        return self.permission != "full"

    @property
    def limit(self) -> int:
        return self.max_files if self.max_files else HARD_RESULT_CAP

    def describe_roots(self) -> list[str]:
        return [str(root) for root in self.roots]


def clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _split_lines(value: object) -> list[str]:
    text = value if isinstance(value, str) else ""
    text = text.replace(";", "\n").replace("|", "\n")
    return [
        item.strip().strip('"').strip("'")
        for item in text.splitlines()
        if item.strip()
    ]


def _expand(raw: str) -> Path | None:
    try:
        expanded = os.path.expandvars(os.path.expanduser(raw))
        candidate = Path(expanded)
        if not candidate.is_absolute():
            candidate = Path.home() / candidate
        return candidate
    except (OSError, RuntimeError, ValueError):
        return None


def _first_existing(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        try:
            resolved = Path(os.path.realpath(candidate))
        except OSError:
            continue
        if resolved.is_dir():
            return resolved
    return None


def _known_folder(kind: str) -> Path | None:
    home = Path.home()
    candidates = {
        "desktop": [home / "Desktop", home / "OneDrive" / "Desktop"],
        "documents": [home / "Documents", home / "OneDrive" / "Documents"],
        "downloads": [home / "Downloads", home / "OneDrive" / "Downloads"],
        "pictures": [home / "Pictures", home / "OneDrive" / "Pictures"],
        "home": [home],
    }.get(kind, [])
    return _first_existing(candidates)


def fixed_drives() -> list[Path]:
    """枚举本机固定磁盘（跳过光驱、U 盘、网络盘）。"""

    if sys.platform != "win32":
        return [Path("/")]
    try:
        kernel32 = ctypes.windll.kernel32
        mask = kernel32.GetLogicalDrives()
        drives: list[Path] = []
        for index in range(26):
            if not mask & (1 << index):
                continue
            letter = f"{chr(ord('A') + index)}:\\"
            if kernel32.GetDriveTypeW(ctypes.c_wchar_p(letter)) == 3:  # DRIVE_FIXED
                drives.append(Path(letter))
        return drives
    except Exception:  # noqa: BLE001 - 枚举失败时退化为系统盘
        return [Path(os.environ.get("SystemDrive", "C:") + "\\")]


def resolve_roots(scope: str, custom_roots: str) -> tuple[tuple[Path, ...], tuple[str, ...]]:
    notes: list[str] = []
    scope = scope if scope in SCOPES else DEFAULTS["scope"]
    if scope == "custom":
        items = _split_lines(custom_roots)
        if not items:
            return (), ("选择了自定义目录，但还没有填写任何目录",)
        roots: list[Path] = []
        for raw in items:
            candidate = _expand(raw)
            if candidate is None:
                notes.append(f"{raw}（路径无效）")
                continue
            try:
                resolved = Path(os.path.realpath(candidate))
            except OSError:
                notes.append(f"{raw}（无法解析）")
                continue
            if resolved.is_dir():
                roots.append(resolved)
            else:
                notes.append(f"{resolved}（目录不存在）")
        return tuple(dict.fromkeys(roots)), tuple(notes)

    if scope == "drives":
        drives = fixed_drives()
        if not drives:
            notes.append("没有找到可用的固定磁盘")
        return tuple(drives), tuple(notes)

    folder = _known_folder(scope)
    if folder is None:
        notes.append(f"找不到“{SCOPES[scope]}”目录")
        return (), tuple(notes)
    return (folder,), tuple(notes)


def build(raw: Mapping[str, Any] | None) -> FileConfig:
    values: Mapping[str, Any] = raw or {}
    scope = str(values.get("scope") or DEFAULTS["scope"])
    custom = str(values.get("custom_roots") or "")
    roots, notes = resolve_roots(scope, custom)
    mode = str(values.get("file_limit_mode") or DEFAULTS["file_limit_mode"])
    max_files: int | None = None
    if mode == "unlimited":
        max_files = None
    else:
        max_files = clamp_int(values.get("max_files"), DEFAULT_MAX_FILES, MIN_FILES, MAX_FILES)
    permission = str(values.get("permission") or DEFAULTS["permission"])
    if permission not in PERMISSIONS:
        permission = DEFAULTS["permission"]
    return FileConfig(
        roots=roots,
        scope=scope,
        max_files=max_files,
        permission=permission,
        notes=notes,
        custom_roots=custom,
    )


def normalize(values: Mapping[str, Any] | None) -> dict[str, Any]:
    values = values or {}
    scope = str(values.get("scope") or DEFAULTS["scope"])
    if scope not in SCOPES:
        scope = DEFAULTS["scope"]
    mode = str(values.get("file_limit_mode") or DEFAULTS["file_limit_mode"])
    if mode not in LIMIT_MODES:
        mode = DEFAULTS["file_limit_mode"]
    permission = str(values.get("permission") or DEFAULTS["permission"])
    if permission not in PERMISSIONS:
        permission = DEFAULTS["permission"]
    return {
        "scope": scope,
        "custom_roots": str(values.get("custom_roots") or ""),
        "file_limit_mode": mode,
        "max_files": clamp_int(values.get("max_files"), DEFAULT_MAX_FILES, MIN_FILES, MAX_FILES),
        "permission": permission,
    }


def warnings_for(config: FileConfig) -> list[str]:
    warnings: list[str] = []
    if config.scope == "drives":
        warnings.append("当前可读全部磁盘")
    if config.max_files is None:
        warnings.append("文件数量不设上限")
    if not config.read_only:
        warnings.append("完全权限已开启，可写入/移动文件")
    return warnings


def status_value(config: FileConfig) -> dict[str, str]:
    if not config.roots:
        detail = "；".join(config.notes)[:200] or "请在设置里选择一个可读目录"
        return {"state": "error", "label": "没有可读目录", "message": detail}
    warnings = warnings_for(config)
    label = f"{config.scope if config.scope in SCOPES else '自定义'}"
    label = SCOPES.get(config.scope, "自定义目录") + f" · {len(config.roots)} 个目录"
    if warnings:
        return {
            "state": "warning",
            "label": label[:120],
            "message": "；".join(warnings + list(config.notes))[:240],
        }
    return {
        "state": "ready",
        "label": label[:120],
        "message": "、".join(str(root) for root in config.roots)[:240],
    }


def settings_descriptor() -> dict[str, Any]:
    return {
        "sectionId": "files",
        "title": "SakuraTools",
        "order": 60,
        "fields": [
            {
                "key": "scope",
                "label": "可访问范围",
                "type": "select",
                "default": DEFAULTS["scope"],
                "options": SCOPE_OPTIONS,
                "description": "选择“全部磁盘”会允许读取所有固定磁盘，风险更高。",
            },
            {
                "key": "custom_roots",
                "label": "自定义目录",
                "type": "string",
                "default": "",
                "maxLength": 8192,
                "enabledWhen": {"field": "scope", "equals": "custom"},
                "description": "每行一个目录，例如 D:\\资料 。",
            },
            {
                "key": "file_limit_mode",
                "label": "文件数量上限",
                "type": "select",
                "default": DEFAULTS["file_limit_mode"],
                "options": LIMIT_OPTIONS,
                "description": "一次最多能列出/搜索到多少个文件。选“不限”时可能一次返回上千个，会拖慢响应并占用大量上下文。",
            },
            {
                "key": "max_files",
                "label": "最多文件数",
                "type": "integer",
                "default": DEFAULT_MAX_FILES,
                "minimum": MIN_FILES,
                "maximum": MAX_FILES,
                "enabledWhen": {"field": "file_limit_mode", "equals": "custom"},
            },
            {
                "key": "permission",
                "label": "写入权限",
                "type": "select",
                "default": DEFAULTS["permission"],
                "options": PERMISSION_OPTIONS,
                "description": "只读：只能查看与读取；完全权限：额外允许新建目录、写入/覆盖文件、移动文件（直接执行，没有二次确认）。",
            },
            {
                "key": "access_status",
                "label": "当前状态",
                "type": "status",
                "default": {"state": "neutral", "label": "未检查", "message": ""},
            },
        ],
        "actions": [{"actionId": "check_access", "label": "检查目录", "danger": False}],
    }
