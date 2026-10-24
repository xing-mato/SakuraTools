"""最小可用的 PDF 文本抽取（纯标准库）。

只做一件事：把页面内容流里的 Tj/TJ 文本取出来，并尽量用 ToUnicode
CMap 还原中文。不做版式还原、不处理加密 PDF；扫描件会明确告知。
"""

from __future__ import annotations

import re
import zlib

_OBJ = re.compile(rb"(\d+)\s+(\d+)\s+obj\b")
_END = re.compile(rb"endobj")
_STREAM = re.compile(rb"stream\r?\n")
_ENDSTREAM = re.compile(rb"\r?\n?endstream")
_BFCHAR = re.compile(rb"beginbfchar(.*?)endbfchar", re.S)
_BFRANGE = re.compile(rb"beginbfrange(.*?)endbfrange", re.S)
_HEX = re.compile(rb"<([0-9A-Fa-f\s]+)>")
_MAX_STREAM = 48 * 1024 * 1024


def _decompress(payload: bytes) -> bytes | None:
    for wbits in (15, -15, 47):
        try:
            return zlib.decompress(payload, wbits)
        except zlib.error:
            continue
    return None


def _parse_objects(data: bytes) -> dict[int, tuple[bytes, bytes | None]]:
    """返回 {对象号: (字典文本, 解压后的流或 None)}。"""

    objects: dict[int, tuple[bytes, bytes | None]] = {}
    position = 0
    while True:
        match = _OBJ.search(data, position)
        if not match:
            break
        number = int(match.group(1))
        body_start = match.end()
        end = _END.search(data, body_start)
        body_end = end.start() if end else min(len(data), body_start + 4 * 1024 * 1024)
        body = data[body_start:body_end]
        position = end.end() if end else body_end
        stream_match = _STREAM.search(body)
        stream: bytes | None = None
        header = body
        if stream_match:
            header = body[: stream_match.start()]
            tail = _ENDSTREAM.search(body, stream_match.end())
            raw = body[stream_match.end() : tail.start() if tail else len(body)]
            if len(raw) > _MAX_STREAM:
                continue
            stream = _decompress(raw) if b"FlateDecode" in header else raw
        objects[number] = (header, stream)
    return objects


def _expand_object_streams(objects: dict[int, tuple[bytes, bytes | None]]) -> dict[int, bytes]:
    """把 /ObjStm 里压缩存放的对象展开成普通字典文本。"""

    expanded: dict[int, bytes] = {}
    for _number, (header, stream) in objects.items():
        if stream is None or b"/ObjStm" not in header:
            continue
        first = re.search(rb"/First\s+(\d+)", header)
        count = re.search(rb"/N\s+(\d+)", header)
        if not first or not count:
            continue
        offset = int(first.group(1))
        numbers = stream[:offset].split()
        try:
            pairs = [(int(numbers[i]), int(numbers[i + 1])) for i in range(0, min(len(numbers) - 1, int(count.group(1)) * 2), 2)]
        except (ValueError, IndexError):
            continue
        for index, (object_number, relative) in enumerate(pairs):
            start = offset + relative
            end = offset + pairs[index + 1][1] if index + 1 < len(pairs) else len(stream)
            expanded.setdefault(object_number, stream[start:end])
    return expanded


def _collect_cmaps(objects: dict[int, tuple[bytes, bytes | None]], extra: dict[int, bytes]) -> tuple[dict[int, str], bool]:
    """合并所有 ToUnicode 映射；返回 ({码值: 字符}, 是否双字节)。"""

    mapping: dict[int, str] = {}
    double_byte = False
    payloads: list[bytes] = [
        stream for _header, stream in objects.values() if stream and (b"beginbfchar" in stream or b"beginbfrange" in stream)
    ]
    for body in extra.values():
        if b"/ToUnicode" in body:
            reference = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", body)
            if reference:
                target = objects.get(int(reference.group(1)))
                if target and target[1]:
                    payloads.append(target[1])

    for payload in payloads:
        for block in _BFCHAR.findall(payload):
            pairs = re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block)
            for source, target in pairs:
                try:
                    code = int(source, 16)
                    text = bytes.fromhex(target.decode("ascii")).decode("utf-16-be", errors="ignore")
                except (ValueError, UnicodeDecodeError):
                    continue
                if text:
                    mapping[code] = text
                    if len(source) > 2:
                        double_byte = True
        for block in _BFRANGE.findall(payload):
            for source, start, values in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]", block, re.S):
                base = int(source, 16)
                for offset, item in enumerate(re.findall(rb"<([0-9A-Fa-f]+)>", values)):
                    try:
                        text = bytes.fromhex(item.decode("ascii")).decode("utf-16-be", errors="ignore")
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if text:
                        mapping[base + offset] = text
                if len(source) > 2:
                    double_byte = True
            for source, start, end in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                try:
                    first, last, target = int(source, 16), int(end, 16), int(start, 16)
                except ValueError:
                    continue
                for code in range(first, min(last, first + 4096) + 1):
                    try:
                        mapping.setdefault(code, chr(target + code - first))
                    except ValueError:
                        continue
    return mapping, double_byte


def _decode_string(raw: bytes, mapping: dict[int, str], double_byte: bool) -> str:
    if not raw:
        return ""
    if mapping and double_byte:
        chars: list[str] = []
        index = 0
        while index < len(raw) - 1:
            code = (raw[index] << 8) | raw[index + 1]
            if code in mapping:
                chars.append(mapping[code])
                index += 2
                continue
            if raw[index] in mapping:
                chars.append(mapping[raw[index]])
                index += 1
                continue
            chars.append("")
            index += 2
        return "".join(chars)
    if mapping:
        return "".join(mapping.get(byte, chr(byte) if 32 <= byte < 127 else "") for byte in raw)
    return raw.decode("latin-1", errors="replace")


def _unescape(raw: bytes) -> bytes:
    out = bytearray()
    index = 0
    escapes = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12,
               ord("("): 40, ord(")"): 41, ord("\\"): 92}
    while index < len(raw):
        byte = raw[index]
        if byte != 92:
            out.append(byte)
            index += 1
            continue
        index += 1
        if index >= len(raw):
            break
        byte = raw[index]
        if byte in escapes:
            out.append(escapes[byte])
            index += 1
        elif 48 <= byte <= 55:
            digits = bytearray()
            while index < len(raw) and len(digits) < 3 and 48 <= raw[index] <= 55:
                digits.append(raw[index])
                index += 1
            out.append(int(digits.decode("ascii"), 8) & 0xFF)
        elif byte in (10, 13):
            index += 1
        else:
            out.append(byte)
            index += 1
    return bytes(out)


def _text_from_content(content: bytes, mapping: dict[int, str], double_byte: bool) -> str:
    parts: list[str] = []
    index = 0
    length = len(content)
    pending: list[bytes] = []

    while index < length:
        byte = content[index]
        if byte == 40:  # (
            depth = 1
            start = index + 1
            index += 1
            while index < length and depth:
                if content[index] == 92:
                    index += 2
                    continue
                if content[index] == 40:
                    depth += 1
                elif content[index] == 41:
                    depth -= 1
                index += 1
            pending.append(_unescape(content[start:index - 1]))
        elif byte == 60 and index + 1 < length and content[index + 1] != 60:  # <hex>
            end = content.find(b">", index)
            if end < 0:
                break
            chunk = re.sub(rb"\s", b"", content[index + 1 : end])
            if len(chunk) % 2:
                chunk += b"0"
            try:
                pending.append(bytes.fromhex(chunk.decode("ascii")))
            except (ValueError, UnicodeDecodeError):
                pass
            index = end + 1
        elif content.startswith(b"TJ", index) or content.startswith(b"Tj", index):
            op = content[index : index + 2]
            index += 2
            if op == b"TJ":
                parts.append(_decode_string(b"".join(pending), mapping, double_byte))
            else:
                parts.append(_decode_string(pending[-1] if pending else b"", mapping, double_byte))
            pending.clear()
        elif content.startswith(b"T*", index) or content.startswith(b"Td", index) or content.startswith(b"TD", index):
            index += 2
            pending.clear()
            parts.append("\n")
        elif content.startswith(b"ET", index):
            index += 2
            parts.append("\n")
        elif byte == 91 or byte == 93:  # [ ]
            index += 1
        else:
            index += 1

    text = "".join(parts).replace("\n\n", "\n")
    return text.strip()


def extract_pdf_text(data: bytes, *, max_chars: int) -> dict[str, object]:
    warnings: list[str] = []
    if b"/Encrypt" in data:
        warnings.append("该 PDF 设置了加密，可能无法完整读取")

    objects = _parse_objects(data)
    if not objects:
        return {"text": "", "pages": 0, "truncated": False, "warnings": ["无法解析 PDF 对象结构"]}
    extra = _expand_object_streams(objects)
    mapping, double_byte = _collect_cmaps(objects, extra)

    contents: list[bytes] = [
        stream
        for _header, stream in objects.values()
        if stream and (b"BT" in stream) and (b"Tj" in stream or b"TJ" in stream)
    ]
    if not contents:
        warnings.append("内容流里没有文本绘制指令")

    pages_text: list[str] = []
    for content in contents:
        text = _text_from_content(content, mapping, double_byte)
        if text:
            pages_text.append(text)

    joined = "\n\n".join(pages_text).strip()
    if joined and mapping and not double_byte:
        printable = sum(1 for char in joined if char.isprintable() or char in "\n\t")
        if printable / max(1, len(joined)) < 0.85:
            warnings.append("部分字符无法映射，正文可能不完整")
    if not joined:
        warnings.append("没有取到正文：可能是扫描件（图片型 PDF）或使用了未嵌入映射的字体")

    truncated = len(joined) > max_chars
    if truncated:
        joined = joined[:max_chars] + "\n…（内容过长已截断）"
    return {"text": joined, "pages": len(pages_text), "truncated": truncated, "warnings": warnings}
