"""图片识别：只读文件头，拿到类型与像素尺寸；不做解码。"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

SUPPORTED = {"png", "jpeg", "gif", "webp", "bmp"}

# 聊天管线接受 data:image/png|jpeg|webp；gif 在多数视觉模型也可用。
ARTIFACT_MEDIA = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}

SUFFIX_MEDIA = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".jfif": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def _png(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    return struct.unpack(">II", data[16:24])


def _gif(data: bytes) -> tuple[int, int] | None:
    if len(data) < 10 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    return struct.unpack("<HH", data[6:10])


def _bmp(data: bytes) -> tuple[int, int] | None:
    if len(data) < 26 or data[:2] != b"BM":
        return None
    width, height = struct.unpack("<ii", data[18:26])
    return abs(width), abs(height)


def _webp(data: bytes) -> tuple[int, int] | None:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    if chunk == b"VP8X":
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return width, height
    if chunk == b"VP8 ":
        if len(data) < 30:
            return None
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return width, height
    if chunk == b"VP8L":
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def _jpeg(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    index = 2
    total = len(data)
    while index + 9 < total:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > total:
            return None
        length = struct.unpack(">H", data[index : index + 2])[0]
        if length < 2:
            return None
        # SOF0..SOF15，排除 DHT(C4) / JPG(C8) / DAC(CC)
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if index + 7 > total:
                return None
            height, width = struct.unpack(">HH", data[index + 3 : index + 7])
            return width, height
        index += length
    return None


def sniff(data: bytes) -> dict[str, Any]:
    """返回 {format, mediaType, width, height, supported}。"""

    for name, parser in (("png", _png), ("jpeg", _jpeg), ("gif", _gif), ("webp", _webp), ("bmp", _bmp)):
        size = parser(data)
        if size is not None:
            width, height = size
            return {
                "format": name,
                "mediaType": ARTIFACT_MEDIA.get(name, f"image/{name}"),
                "width": int(width),
                "height": int(height),
                "supported": name in SUPPORTED,
            }
    return {"format": "", "mediaType": "", "width": 0, "height": 0, "supported": False}


def read_header(path: Path, limit: int = 512 * 1024) -> bytes:
    with path.open("rb") as handle:
        return handle.read(limit)
