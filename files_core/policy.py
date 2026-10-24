"""路径策略：解析、越界检查与敏感文件过滤。

只读/写入都先过这里：路径必须落在允许范围内，且不命中敏感名单。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from .config import FileConfig
from .errors import FilesError

# 始终拒绝的敏感目录名（凭据、浏览器配置、系统凭据库）。
SENSITIVE_DIRS = frozenset(
    {
        ".ssh",
        ".gnupg",
        ".aws",
        ".azure",
        ".kube",
        ".docker",
        ".password-store",
        "credentials",
        "protect",
        "cookies",
        "login data",
    }
)

SENSITIVE_NAMES = frozenset(
    {
        "ntuser.dat",
        "sam",
        "security",
        "system",
        "local state",
        "login data",
        "login data for account",
        "web data",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "known_hosts",
        "wallet.dat",
        "index.dat",
    }
)

SENSITIVE_SUFFIXES = (
    ".pem",
    ".key",
    ".pfx",
    ".p12",
    ".kdbx",
    ".jks",
    ".keystore",
    ".ost",
    ".pst",
    ".hive",
)

SENSITIVE_FRAGMENTS = (
    "\\appdata\\roaming\\microsoft\\credentials",
    "\\appdata\\roaming\\microsoft\\protect",
    "\\appdata\\local\\google\\chrome\\user data",
    "\\appdata\\roaming\\mozilla\\firefox\\profiles",
    "\\appdata\\local\\microsoft\\edge\\user data",
    "\\appdata\\local\\microsoft\\credentials",
    "\\windows\\system32\\config",
)


def _norm(path: Path | str) -> str:
    return os.path.normcase(os.path.realpath(str(path)))


def _posix(path: str) -> str:
    return path.replace("\\", "/").casefold()


def within(path: Path, root: Path) -> bool:
    target = _norm(path)
    base = _norm(root)
    return target == base or target.startswith(base.rstrip(os.sep) + os.sep)


def within_any(path: Path, roots: Iterable[Path]) -> bool:
    return any(within(path, root) for root in roots)


def deny_reason(path: Path) -> str:
    """返回拒绝原因；空串表示可以访问。"""

    text = _posix(_norm(path))
    parts = {part.casefold() for part in path.parts}
    name = path.name.casefold()

    if parts & SENSITIVE_DIRS:
        return "命中敏感目录名单"
    if name in SENSITIVE_NAMES:
        return "命中敏感文件名名单"
    if name.endswith(SENSITIVE_SUFFIXES):
        return "敏感文件类型"
    for fragment in SENSITIVE_FRAGMENTS:
        if _posix(fragment) in text:
            return "命中系统凭据或浏览器配置目录"
    return ""


def resolve(raw_path: str, config: FileConfig, *, base: Path | None = None) -> Path:
    """把模型给的路径解析成真实路径，并保证它在允许范围内。"""

    if not isinstance(raw_path, str) or not raw_path.strip():
        raise FilesError("FILES_INVALID_ARGUMENT", "path 不能为空")
    if not config.roots:
        raise FilesError("FILES_NO_ROOT", "还没有可读目录，请先在插件设置里选择可访问范围")
    raw = os.path.expandvars(os.path.expanduser(raw_path.strip().strip('"')))
    candidate = Path(raw)
    if not candidate.is_absolute():
        anchor = base or config.roots[0]
        candidate = anchor / candidate
    try:
        resolved = Path(os.path.realpath(candidate))
    except OSError as error:
        raise FilesError("FILES_IO_ERROR", f"路径无法解析：{raw_path}") from error

    if not within_any(resolved, config.roots):
        raise FilesError("FILES_OUTSIDE_ROOT", "该路径不在允许访问的范围内")
    reason = deny_reason(resolved)
    if reason:
        raise FilesError("FILES_DENIED", f"出于安全考虑拒绝访问：{reason}")
    if not resolved.exists():
        raise FilesError("FILES_NOT_FOUND", f"路径不存在：{resolved}")
    return resolved


def resolve_new(raw_path: str, config: FileConfig) -> Path:
    """解析一个可能还不存在的目标路径（写入/新建目录用）。"""

    if not isinstance(raw_path, str) or not raw_path.strip():
        raise FilesError("FILES_INVALID_ARGUMENT", "path 不能为空")
    if not config.roots:
        raise FilesError("FILES_NO_ROOT", "还没有可读目录，请先在插件设置里选择可访问范围")
    raw = os.path.expandvars(os.path.expanduser(raw_path.strip().strip('"')))
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = config.roots[0] / candidate
    try:
        resolved = Path(os.path.realpath(candidate))
    except OSError as error:
        raise FilesError("FILES_IO_ERROR", f"路径无法解析：{raw_path}") from error
    if not within_any(resolved, config.roots):
        raise FilesError("FILES_OUTSIDE_ROOT", "该路径不在允许访问的范围内")
    reason = deny_reason(resolved)
    if reason:
        raise FilesError("FILES_DENIED", f"出于安全考虑拒绝写入：{reason}")
    return resolved
