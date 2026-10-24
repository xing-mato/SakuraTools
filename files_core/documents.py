"""文档正文抽取：Office / ODF / EPUB / HTML / RTF，全部走标准库。

目标不是版式还原，而是“把正文取出来给模型读”。
"""

from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .errors import FilesError

DOCUMENT_SUFFIXES = {
    ".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm",
    ".odt", ".ods", ".odp", ".epub", ".html", ".htm", ".xhtml", ".rtf", ".pdf",
}

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".jfif", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".ico", ".svg"}

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
OPF = "{http://www.idpf.org/2007/opf}"
CONTAINER = "{urn:oasis:names:tc:opendocument:xmlns:container}"

MAX_ROWS = 300
MAX_COLUMNS = 24
MAX_SLIDES = 80
MAX_EPUB_SECTIONS = 60


def kind_for(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in DOCUMENT_SUFFIXES:
        return "document"
    return "text"


def _read_member(archive: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    if info.file_size > 64 * 1024 * 1024:
        raise FilesError("FILES_TOO_LARGE", "压缩包内单个部件的体积异常")
    with archive.open(info) as handle:
        return handle.read()


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _docx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        payload = _read_member(archive, "word/document.xml")
    if payload is None:
        raise FilesError("FILES_UNSUPPORTED", "DOCX 里找不到正文部件")
    root = ElementTree.fromstring(payload)
    body = root.find(W + "body")
    if body is None:
        body = root
    chunks: list[str] = []

    def paragraph(node) -> str:
        parts: list[str] = []
        for child in node.iter():
            if child.tag == W + "t":
                parts.append(child.text or "")
            elif child.tag == W + "tab":
                parts.append("\t")
            elif child.tag in (W + "br", W + "cr"):
                parts.append("\n")
        return "".join(parts)

    for child in body:
        if child.tag == W + "p":
            chunks.append(paragraph(child))
        elif child.tag == W + "tbl":
            for row in child.iter(W + "tr"):
                cells = [paragraph(cell).replace("\n", " ").strip() for cell in row.iter(W + "tc")]
                chunks.append(" | ".join(cells))
        elif child.tag == W + "sdt":
            for nested in child.iter(W + "p"):
                chunks.append(paragraph(nested))
    return _clean("\n".join(chunks))


def _xlsx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        shared_payload = _read_member(archive, "xl/sharedStrings.xml")
        if shared_payload:
            shared_root = ElementTree.fromstring(shared_payload)
            for item in shared_root.iter(S + "si"):
                shared.append("".join(node.text or "" for node in item.iter(S + "t")))
        sheet_names: dict[str, str] = {}
        workbook = _read_member(archive, "xl/workbook.xml")
        if workbook:
            workbook_root = ElementTree.fromstring(workbook)
            for index, sheet in enumerate(workbook_root.iter(S + "sheet"), start=1):
                name = sheet.get("name") or f"Sheet{index}"
                rel = sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id") or ""
                sheet_names[rel] = name
        rels: dict[str, str] = {}
        rels_payload = _read_member(archive, "xl/_rels/workbook.xml.rels")
        if rels_payload:
            rels_root = ElementTree.fromstring(rels_payload)
            for rel in rels_root:
                rels[rel.get("Id") or ""] = rel.get("Target") or ""
        targets = [
            (sheet_names.get(rel_id, ""), ("xl/" + target).replace("xl//", "xl/"))
            for rel_id, target in rels.items()
            if target.casefold().endswith(".xml")
        ]
        if not targets:
            targets = [
                (name.rsplit("/", 1)[-1], name)
                for name in archive.namelist()
                if name.startswith("xl/worksheets/") and name.endswith(".xml")
            ]

    blocks: list[str] = []
    for sheet_name, member in targets:
        with zipfile.ZipFile(path) as archive:
            payload = _read_member(archive, member)
        if not payload:
            continue
        root = ElementTree.fromstring(payload)
        rows: list[str] = []
        for row_index, row in enumerate(root.iter(S + "row")):
            if row_index >= MAX_ROWS:
                rows.append("…（表格过长已截断）")
                break
            cells: list[str] = []
            for cell in row.iter(S + "c"):
                kind = cell.get("t") or ""
                value = ""
                if kind == "s":
                    raw = cell.find(S + "v")
                    try:
                        value = shared[int(raw.text or "0")]
                    except (AttributeError, ValueError, IndexError):
                        value = ""
                elif kind == "inlineStr":
                    node = cell.find(S + "is")
                    value = "".join(text.text or "" for text in node.iter(S + "t")) if node is not None else ""
                else:
                    raw = cell.find(S + "v")
                    value = raw.text if raw is not None and raw.text else ""
                if value:
                    cells.append(value.strip().replace("\n", " "))
                if len(cells) >= MAX_COLUMNS:
                    cells.append("…")
                    break
            if any(cells):
                rows.append(" | ".join(cells))
        if rows:
            blocks.append(f"[工作表] {sheet_name or '未命名'}\n" + "\n".join(rows))
    return _clean("\n\n".join(blocks))


def _pptx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        slides = sorted(
            (name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
            key=lambda name: int(re.search(r"(\d+)", name.rsplit("/", 1)[-1]).group(1)),  # type: ignore[union-attr]
        )
        blocks: list[str] = []
        for index, member in enumerate(slides[:MAX_SLIDES], start=1):
            payload = _read_member(archive, member)
            if not payload:
                continue
            root = ElementTree.fromstring(payload)
            lines = []
            for paragraph in root.iter(A + "p"):
                text = "".join(node.text or "" for node in paragraph.iter(A + "t")).strip()
                if text:
                    lines.append(text)
            if lines:
                blocks.append(f"[第 {index} 页]\n" + "\n".join(lines))
    return _clean("\n\n".join(blocks))


def _opendocument(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        payload = _read_member(archive, "content.xml")
    if payload is None:
        raise FilesError("FILES_UNSUPPORTED", "ODF 文件里找不到 content.xml")
    root = ElementTree.fromstring(payload)
    chunks: list[str] = []
    for node in root.iter():
        if node.tag in (TEXT + "p", TEXT + "h", TEXT + "list-item"):
            text = "".join(node.itertext())
            if text.strip():
                chunks.append(text.strip())
        elif node.tag == TABLE + "table-row":
            cells = ["".join(cell.itertext()).strip() for cell in node.findall(TABLE + "table-cell")]
            if any(cells):
                chunks.append(" | ".join(cells))
    return _clean("\n".join(chunks))


def _html_to_text(markup: str) -> str:
    from html.parser import HTMLParser

    class _Extractor(HTMLParser):
        block = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table"}
        skip = {"script", "style", "noscript", "template", "svg"}

        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []
            self.depth_skip = 0

        def handle_starttag(self, tag, attrs):
            if tag in self.skip:
                self.depth_skip += 1
            elif tag in self.block:
                self.parts.append("\n")

        def handle_endtag(self, tag):
            if tag in self.skip and self.depth_skip:
                self.depth_skip -= 1
            elif tag in self.block:
                self.parts.append("\n")

        def handle_data(self, data):
            if not self.depth_skip:
                self.parts.append(data)

    parser = _Extractor()
    parser.feed(markup)
    parser.close()
    return _clean("".join(parser.parts))


def _epub(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        root_path = ""
        payload = _read_member(archive, "META-INF/container.xml")
        if payload:
            root = ElementTree.fromstring(payload)
            for node in root.iter(CONTAINER + "rootfile"):
                root_path = node.get("full-path") or ""
                break
        order: list[str] = []
        if root_path:
            opf_payload = _read_member(archive, root_path)
            if opf_payload:
                opf = ElementTree.fromstring(opf_payload)
                manifest = {
                    item.get("id") or "": item.get("href") or ""
                    for item in opf.iter(OPF + "item")
                }
                base = root_path.rsplit("/", 1)[0] + "/" if "/" in root_path else ""
                for ref in opf.iter(OPF + "itemref"):
                    href = manifest.get(ref.get("idref") or "")
                    if href:
                        order.append((base + href).replace("//", "/").lstrip("./"))
        if not order:
            order = [name for name in archive.namelist() if name.casefold().endswith((".xhtml", ".html", ".htm"))]
        blocks: list[str] = []
        for member in order[:MAX_EPUB_SECTIONS]:
            payload = _read_member(archive, member)
            if not payload:
                continue
            text = _html_to_text(payload.decode("utf-8", errors="replace"))
            if text:
                blocks.append(text)
    return _clean("\n\n".join(blocks))


_RTF_UNICODE = re.compile(r"\\u(-?\d+)\s?\??")
_RTF_HEX = re.compile(r"\\'([0-9a-fA-F]{2})")
_RTF_CONTROL = re.compile(r"\\[a-zA-Z]+-?\d*\s?")


def _rtf(path: Path) -> str:
    raw = path.read_text(encoding="latin-1", errors="replace")
    raw = raw.replace("\\par", "\n").replace("\\line", "\n").replace("\\tab", "\t")

    def unicode_escape(match: re.Match[str]) -> str:
        code = int(match.group(1))
        if code < 0:
            code += 65536
        try:
            return chr(code)
        except ValueError:
            return ""

    raw = _RTF_UNICODE.sub(unicode_escape, raw)

    def hex_escape(match: re.Match[str]) -> str:
        byte = int(match.group(1), 16)
        return bytes([byte]).decode("cp1252", errors="replace")

    raw = _RTF_HEX.sub(hex_escape, raw)
    raw = _RTF_CONTROL.sub("", raw)
    raw = raw.replace("\\{", "{").replace("\\}", "}").replace("\\\\", "\\")
    raw = raw.replace("{", "").replace("}", "")
    return _clean(raw)


def extract_document(path: Path, *, max_chars: int) -> dict[str, object]:
    suffix = path.suffix.casefold()
    if suffix in {".docx", ".docm"}:
        text = _docx(path)
    elif suffix in {".xlsx", ".xlsm"}:
        text = _xlsx(path)
    elif suffix in {".pptx", ".pptm"}:
        text = _pptx(path)
    elif suffix in {".odt", ".ods", ".odp"}:
        text = _opendocument(path)
    elif suffix == ".epub":
        text = _epub(path)
    elif suffix in {".html", ".htm", ".xhtml"}:
        text = _html_to_text(path.read_text(encoding="utf-8", errors="replace"))
    elif suffix == ".rtf":
        text = _rtf(path)
    elif suffix == ".pdf":
        from .pdf import extract_pdf_text

        result = extract_pdf_text(path.read_bytes(), max_chars=max_chars)
        return {"kind": "document", "format": "pdf", "text": result["text"], "pages": result["pages"],
                "truncated": result["truncated"], "warnings": result["warnings"]}
    else:
        raise FilesError("FILES_UNSUPPORTED", f"暂不支持抽取 {suffix or '未知'} 格式的正文")

    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars] + "\n…（内容过长已截断）"
    if not text.strip():
        raise FilesError("FILES_EMPTY", "没有抽取到正文；可能是扫描件、空文档或加密文档")
    return {"kind": "document", "format": suffix.lstrip("."), "text": text, "truncated": truncated}
