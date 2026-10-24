"""文本文件读取：编码探测、行号、截断与体积上限。"""

from __future__ import annotations

from pathlib import Path

from .decode import decode_text, looks_binary
from .errors import FilesError

MAX_LINE_CHARS = 480


def _format_lines(lines: list[str], start: int) -> str:
    width = len(str(start + len(lines) - 1)) if lines else 1
    formatted: list[str] = []
    for offset, line in enumerate(lines):
        number = start + offset
        body = line.rstrip("\r\n")
        if len(body) > MAX_LINE_CHARS:
            body = body[:MAX_LINE_CHARS] + f" …（本行还有 {len(body) - MAX_LINE_CHARS} 字符）"
        formatted.append(f"{str(number).rjust(width)}│ {body}")
    return "\n".join(formatted)


def read_text_file(
    path: Path,
    *,
    max_bytes: int,
    max_chars: int,
    start_line: int = 1,
    max_lines: int = 0,
) -> dict[str, object]:
    size = path.stat().st_size
    if size > max_bytes:
        raise FilesError(
            "FILES_TOO_LARGE",
            f"文件 {size // 1024} KB 超过上限 {max_bytes // 1024 // 1024} MB；可在设置里调大“单个文件上限”",
        )
    data = path.read_bytes()
    if looks_binary(data[:8192]):
        raise FilesError("FILES_BINARY", "看起来是二进制文件，无法按文本读取；图片请用 files__read_image")
    text, encoding = decode_text(data)

    total_lines = text.count("\n") + (0 if text.endswith("\n") else 1) if text else 0
    lines = text.splitlines()
    start = max(1, int(start_line or 1))
    if start > len(lines):
        return {
            "path": str(path),
            "kind": "text",
            "encoding": encoding,
            "totalLines": total_lines,
            "startLine": start,
            "returnedLines": 0,
            "text": "",
            "truncated": False,
            "note": f"文件只有 {total_lines} 行",
        }

    limit = int(max_lines or 0)
    selected = lines[start - 1 :]
    if limit > 0:
        selected = selected[:limit]
    formatted = _format_lines(selected, start)
    truncated = len(formatted) > max_chars
    if truncated:
        formatted = formatted[:max_chars] + "\n…（内容过长已截断，可用 start_line / max_lines 继续）"

    return {
        "path": str(path),
        "kind": "text",
        "encoding": encoding,
        "totalLines": total_lines,
        "startLine": start,
        "returnedLines": len(selected),
        "text": formatted,
        "truncated": truncated or (start - 1 + len(selected)) < len(lines),
    }
