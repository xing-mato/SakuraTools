"""文本解码：优先 UTF-8，其次中文/繁体常见编码，并识别二进制。"""

from __future__ import annotations

import re

_BOM_HANDLERS = (
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe\x00\x00", "utf-32"),
    (b"\x00\x00\xfe\xff", "utf-32"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3000-\u303f\uff00-\uffef]")
_COMMON_ASCII = re.compile(r"[\x20-\x7e\n\r\t]")
_RARE = re.compile(r"[\u0100-\u2fff\ue000-\uf8ff\ufffd]")


def looks_binary(head: bytes) -> bool:
    """前 8 KiB 出现 NUL 且没有 UTF-16 BOM，基本可判为二进制。"""

    if not head:
        return False
    if head.startswith(b"\xff\xfe") or head.startswith(b"\xfe\xff"):
        return False
    sample = head[:8192]
    if b"\x00" not in sample:
        return False
    # 允许 UTF-16 无 BOM：偶数位大量 NUL 的情况单独放行给解码阶段判定。
    zeros_even = sample[0::2].count(0)
    zeros_odd = sample[1::2].count(0)
    return not (zeros_even > len(sample) // 4 or zeros_odd > len(sample) // 4)


def _score(text: str) -> int:
    """粗评分：常用字符越多、怪异字符越少，得分越高。"""

    if not text:
        return 0
    sample = text[:8000]
    good = len(_CJK.findall(sample)) * 3 + len(_COMMON_ASCII.findall(sample))
    bad = len(_RARE.findall(sample)) * 4 + text.count("\ufffd") * 8
    return good - bad


def decode_text(data: bytes, hint: str | None = None) -> tuple[str, str]:
    """返回 (文本, 编码名)。无法确定时按拉丁字母兜底。"""

    if hint:
        try:
            return data.decode(hint), hint
        except (LookupError, UnicodeDecodeError):
            pass
    for bom, encoding in _BOM_HANDLERS:
        if data.startswith(bom):
            try:
                return data.decode(encoding), encoding
            except UnicodeDecodeError:
                break

    candidates: list[tuple[str, str]] = []
    for encoding in ("utf-8", "gb18030", "big5", "cp1252"):
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        candidates.append((encoding, text))

    if not candidates:
        return data.decode("latin-1", errors="replace"), "latin-1"

    best_encoding, best_text = max(candidates, key=lambda item: _score(item[1]))
    if best_encoding == "cp1252" and _score(best_text) <= 0:
        return data.decode("latin-1", errors="replace"), "latin-1"
    return best_text, best_encoding
