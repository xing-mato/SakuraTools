"""离线自检：生成临时样例，跑一遍只读与写入两条路径。

用法（在本目录下）：
    python selftest.py        （用 Sakura 自带的 python.exe 也可以）
临时文件都放在本目录的 .selftest-tmp 里，跑完自动删除。
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import sys

# Windows 控制台默认不是 UTF-8（GitHub Actions 上是 cp1252），
# 直接 print 中文会抛 UnicodeEncodeError。这里显式切成 UTF-8。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from files_core import config as file_config  # noqa: E402
from files_core import handlers  # noqa: E402
from files_core.errors import FilesError  # noqa: E402

TMP = HERE / ".selftest-tmp"
ARTIFACTS = TMP / "artifacts"

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class FakeArtifacts:
    """模拟 sakura.host.artifacts。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.allocations: dict[str, dict] = {}
        self.counter = 0

    def allocate(self, descriptor: dict) -> dict:
        self.counter += 1
        artifact_id = f"artifact-{self.counter}"
        path = self.root / f"{artifact_id}{descriptor['suffix']}"
        self.allocations[artifact_id] = {"path": path, "mediaType": descriptor["mediaType"]}
        return {"artifactId": artifact_id, "path": str(path), "mediaType": descriptor["mediaType"]}

    def commit(self, artifact_id: str) -> dict:
        item = self.allocations[artifact_id]
        return {"artifactId": artifact_id, "mediaType": item["mediaType"], "byteLength": item["path"].stat().st_size}

    def release(self, artifact_id: str) -> bool:
        self.allocations.pop(artifact_id, None)
        return True


def build_docx(path: Path) -> None:
    document = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        "<w:p><w:r><w:t>第一段：主人的名字是星。</w:t></w:r></w:p>"
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>B</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
        "</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)


def build_xlsx(path: Path) -> None:
    shared = (
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<si><t>名称</t></si><si><t>数量</t></si><si><t>苹果</t></si></sst>"
    )
    workbook = (
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="清单" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
    )
    sheet = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
        '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>3</v></c></row>'
        "</sheetData></worksheet>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", shared)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


def build_pptx(path: Path) -> None:
    slide = (
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>'
        "<p:sp><p:txBody><a:p><a:r><a:t>封面标题</a:t></a:r></a:p>"
        "<a:p><a:r><a:t>副标题</a:t></a:r></a:p></p:txBody></p:sp>"
        "</p:spTree></p:cSld></p:sld>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", slide)


def build_pdf(path: Path) -> None:
    content = b"BT /F1 12 Tf 20 100 Td (Hello Sakura PDF) Tj ET"
    path.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
        b"2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj\n"
        b"3 0 obj <</Type /Page /Parent 2 0 R /Contents 4 0 R>> endobj\n"
        + b"4 0 obj <</Length " + str(len(content)).encode() + b">> stream\n" + content + b"\nendstream endobj\n"
        b"trailer <</Root 1 0 R>>\n%%EOF\n"
    )


def build_pdf_cjk(path: Path) -> None:
    """带 Identity-H 字体与 ToUnicode 的中文 PDF（模拟 WPS/Word 导出）。"""

    cmap = (
        b"/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        b"/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
        b"1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
        b"2 beginbfchar\n<0001> <8BB0>\n<0002> <5FC6>\nendbfchar\n"
        b"endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
    )
    content = b"BT /F1 12 Tf 20 100 Td <00010002> Tj ET"
    path.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
        b"2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj\n"
        b"3 0 obj <</Type /Page /Parent 2 0 R /Contents 4 0 R "
        b"/Resources <</Font <</F1 5 0 R>>>>>> endobj\n"
        + b"4 0 obj <</Length " + str(len(content)).encode() + b">> stream\n" + content + b"\nendstream endobj\n"
        b"5 0 obj <</Type /Font /Subtype /Type0 /BaseFont /SimSun /Encoding /Identity-H /ToUnicode 6 0 R>> endobj\n"
        + b"6 0 obj <</Length " + str(len(cmap)).encode() + b">> stream\n" + cmap + b"\nendstream endobj\n"
        b"trailer <</Root 1 0 R>>\n%%EOF\n"
    )


def build_html(path: Path) -> None:
    path.write_text(
        "<html><head><style>p{}</style><script>var x=1;</script></head>"
        "<body><h1>标题</h1><p>正文段落</p></body></html>",
        encoding="utf-8",
    )


def prepare() -> None:
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)
    (TMP / "notes").mkdir()
    (TMP / "notes" / "记忆.txt").write_text("记忆：主人喜欢安静。\n第二行\n", encoding="utf-8")
    (TMP / "notes" / "gbk.txt").write_bytes("这是 GBK 编码的文件，里面有中文。".encode("gbk"))
    (TMP / "notes" / "todo.md").write_text("# 待办\n- 修好插件\n", encoding="utf-8")
    (TMP / "data.json").write_text(json.dumps({"名字": "星"}, ensure_ascii=False), encoding="utf-8")
    (TMP / "screenshot.png").write_bytes(PNG_1PX)
    build_docx(TMP / "report.docx")
    build_xlsx(TMP / "sheet.xlsx")
    build_pptx(TMP / "slides.pptx")
    build_pdf(TMP / "manual.pdf")
    build_pdf_cjk(TMP / "chinese.pdf")
    build_html(TMP / "page.html")


class Harness:
    def __init__(self) -> None:
        self.config = {
            "scope": "custom",
            "custom_roots": str(TMP),
            "file_limit_mode": "custom",
            "max_files": 50,
            "permission": "read_only",
        }
        self.artifacts = FakeArtifacts(ARTIFACTS)
        self.runtime = handlers.Runtime(lambda: self.config, None, self.artifacts)
        self.failures: list[str] = []

    def call(self, name: str, **arguments):
        return self.runtime.call(name, arguments)

    def expect(self, condition: bool, label: str, detail: str = "") -> None:
        if condition:
            print(f"  PASS  {label}")
        else:
            print(f"  FAIL  {label} {detail}")
            self.failures.append(label)


class FakeConfig:
    def __init__(self, values: dict) -> None:
        self.values = dict(values)

    def get(self) -> dict:
        return dict(self.values)

    def update(self, values: dict) -> str:
        self.values.update(values)
        return "ok"

    def on_change(self, handler):
        return lambda: None


class RecordingTools:
    def __init__(self) -> None:
        self.handlers: dict = {}

    def register(self, descriptor: dict, handler):
        name = descriptor["name"]
        assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name), name
        assert descriptor.get("description"), name
        assert descriptor.get("risk") in {"low", "medium", "high"}, name
        assert isinstance(descriptor.get("parameters"), dict), name
        self.handlers[name] = handler
        return {"registrationId": f"reg-{len(self.handlers)}"}


class RecordingSettings:
    def register(self, descriptor, *, load, save, actions):
        self.descriptor = descriptor
        self.handlers = {"load": load, "save": save, **{"action:" + key: value for key, value in actions.items()}}
        return {"registrationId": "settings-1"}


class FakeLogger:
    def debug(self, message, *, fields=None): return True
    def info(self, message, *, fields=None): return True
    def warning(self, message, *, fields=None): return True
    def error(self, message, *, fields=None): return True


class FakeContext:
    plugin_id = "sakuratools.files"

    def __init__(self, config: dict, artifacts) -> None:
        self.config = FakeConfig(config)
        self.tools = RecordingTools()
        self.settings = RecordingSettings()
        self.cleanups = []
        self.services = {
            "sakura.host.tools": self.tools,
            "sakura.host.logging": FakeLogger(),
            "sakura.host.settings": self.settings,
            "sakura.host.artifacts": artifacts,
        }

    def get(self, key):
        if key not in self.services:
            raise KeyError(key)
        return self.services[key]

    def effect(self, cleanup):
        self.cleanups.append(cleanup)
        return lambda: None

    def provide(self, *args, **kwargs):
        return lambda: None

    def on(self, *args, **kwargs):
        return lambda: None

    def data_path(self, relative):
        return TMP / relative


def check_setup(harness: Harness) -> None:
    """走真实入口：plugin.setup() → 注册 → 调用 → 设置页。"""

    from plugin import FilesPlugin

    context = FakeContext(dict(harness.config), FakeArtifacts(ARTIFACTS))
    plugin = FilesPlugin()
    plugin.setup(context)

    harness.expect(len(context.tools.handlers) == 9, "注册 9 个工具", str(sorted(context.tools.handlers)))
    harness.expect(
        all(name.startswith("files__") for name in context.tools.handlers),
        "工具名都有 files__ 前缀",
    )
    read = context.tools.handlers["files__read"]({"path": str(TMP / "notes" / "记忆.txt")})
    harness.expect("记忆" in str(read.get("text", "")), "入口注册的 read 可执行")
    image = context.tools.handlers["files__read_image"]({"path": str(TMP / "screenshot.png")})
    harness.expect(isinstance(image.get("artifact"), dict), "入口注册的 read_image 产出工件")

    view = context.settings.handlers["load"]()
    harness.expect(
        set(view) == {"scope", "custom_roots", "file_limit_mode", "max_files", "permission", "access_status"},
        "设置 load 返回完整字段",
        str(sorted(view)),
    )
    context.settings.handlers["save"]({
        "scope": "custom", "custom_roots": str(TMP), "file_limit_mode": "unlimited",
        "max_files": 30, "permission": "full",
    })
    harness.expect(
        context.config.values["permission"] == "full" and context.config.values["file_limit_mode"] == "unlimited",
        "设置 save 落盘",
    )
    status = context.settings.handlers["action:check_access"]({
        "scope": "custom", "custom_roots": str(TMP), "file_limit_mode": "unlimited",
        "max_files": 30, "permission": "full",
    })
    harness.expect(status["access_status"]["state"] == "warning", "不限条数/完全权限时状态为警告", str(status))

    for cleanup in context.cleanups:
        cleanup()
    closed = context.tools.handlers["files__list"]({"path": str(TMP)})
    harness.expect(closed.get("reasonCode") == "FILES_NOT_READY", "close 后拒绝调用", str(closed))


def main() -> int:
    prepare()
    harness = Harness()
    print("文件工具自检")

    text = harness.call("files__read", path=str(TMP / "notes" / "记忆.txt"))
    harness.expect("记忆" in str(text.get("text", "")), "UTF-8 文本读取", str(text)[:160])
    harness.expect("1│" in str(text.get("text", "")), "输出带行号")

    gbk = harness.call("files__read", path=str(TMP / "notes" / "gbk.txt"))
    harness.expect("GBK" in str(gbk.get("text", "")), "GBK 自动解码", str(gbk)[:160])

    docx = harness.call("files__read", path=str(TMP / "report.docx"))
    harness.expect("第一段" in str(docx.get("text", "")), "DOCX 正文抽取", str(docx)[:160])
    harness.expect("A | B" in str(docx.get("text", "")), "DOCX 表格抽取")

    xlsx = harness.call("files__read", path=str(TMP / "sheet.xlsx"))
    harness.expect("苹果" in str(xlsx.get("text", "")) and "清单" in str(xlsx.get("text", "")), "XLSX 抽取", str(xlsx)[:200])

    pptx = harness.call("files__read", path=str(TMP / "slides.pptx"))
    harness.expect("封面标题" in str(pptx.get("text", "")), "PPTX 抽取")

    pdf = harness.call("files__read", path=str(TMP / "manual.pdf"))
    harness.expect("Hello Sakura PDF" in str(pdf.get("text", "")), "PDF 抽取")

    cjk = harness.call("files__read", path=str(TMP / "chinese.pdf"))
    harness.expect("记忆" in str(cjk.get("text", "")), "中文 PDF 走 ToUnicode 映射", str(cjk)[:200])

    page = harness.call("files__read", path=str(TMP / "page.html"))
    harness.expect("正文段落" in str(page.get("text", "")) and "var x" not in str(page.get("text", "")), "HTML 抽取并跳过脚本")

    image = harness.call("files__read_image", path=str(TMP / "screenshot.png"))
    harness.expect(isinstance(image.get("artifact"), dict), "图片返回工件描述符", str(image)[:200])
    harness.expect(set(image) == {"content", "artifact"}, "图片信封只含 content/artifact", str(sorted(image)))
    harness.expect("1x1" in str(image.get("content", "")), "图片尺寸写进 content")
    artifact_id = str(image.get("artifact", {}).get("artifactId", ""))
    artifact_path = harness.artifacts.allocations.get(artifact_id, {}).get("path")
    harness.expect(
        isinstance(artifact_path, Path) and artifact_path.exists() and artifact_path.read_bytes() == PNG_1PX,
        "工件字节与源文件一致",
    )

    wrong = harness.call("files__read", path=str(TMP / "screenshot.png"))
    harness.expect(wrong.get("reasonCode") == "FILES_IS_IMAGE", "图片误用 read 时给出提示", str(wrong))

    listing = harness.call("files__list", path=str(TMP / "notes"), pattern="*.md")
    names = [item.get("name") for item in listing.get("entries", [])]
    harness.expect(any("todo.md" in str(name) for name in names), "按通配符列目录", str(names))

    found = harness.call("files__find", root=str(TMP), pattern="*.pdf")
    harness.expect(found.get("count", 0) >= 2, "按文件名查找", str(found)[:160])

    hits = harness.call("files__grep", root=str(TMP), query="记忆")
    harness.expect(hits.get("count", 0) >= 1, "目录内文本搜索", str(hits)[:200])

    stat = harness.call("files__stat", path=str(TMP / "screenshot.png"))
    harness.expect(stat.get("width") == 1 and "sha256" in stat, "文件属性与哈希")

    outside = harness.call("files__read", path=str(Path.home() / ".." / "Windows" / "win.ini"))
    harness.expect(outside.get("reasonCode") in {"FILES_OUTSIDE_ROOT", "FILES_NOT_FOUND", "FILES_DENIED"}, "越界路径被拒绝", str(outside))

    secret = TMP / ".ssh"
    secret.mkdir(exist_ok=True)
    (secret / "id_rsa").write_text("私钥", encoding="utf-8")
    denied = harness.call("files__read", path=str(secret / "id_rsa"))
    harness.expect(denied.get("reasonCode") == "FILES_DENIED", "敏感目录被拒绝", str(denied))

    # 只读模式：写入类工具必须被拒绝
    blocked = harness.call("files__write", path=str(TMP / "new.txt"), content="x")
    harness.expect(blocked.get("reasonCode") == "FILES_READ_ONLY", "只读模式拒绝写入", str(blocked))
    blocked_dir = harness.call("files__mkdir", path=str(TMP / "newdir"))
    harness.expect(blocked_dir.get("reasonCode") == "FILES_READ_ONLY", "只读模式拒绝建目录", str(blocked_dir))

    # 切到完全权限
    harness.config["permission"] = "full"
    written = harness.call("files__write", path=str(TMP / "written.txt"), content="第一行\n")
    harness.expect(written.get("created") is True and (TMP / "written.txt").read_text(encoding="utf-8") == "第一行\n", "完全权限下写入文件", str(written))
    harness.call("files__write", path=str(TMP / "written.txt"), content="第二行\n", mode="append")
    harness.expect((TMP / "written.txt").read_text(encoding="utf-8") == "第一行\n第二行\n", "追加写入")
    made = harness.call("files__mkdir", path=str(TMP / "newdir" / "sub"))
    harness.expect(made.get("created") is True and (TMP / "newdir" / "sub").is_dir(), "新建多级目录", str(made))
    moved = harness.call("files__move", source=str(TMP / "written.txt"), destination=str(TMP / "moved.txt"))
    harness.expect(moved.get("moved") is True and (TMP / "moved.txt").is_file() and not (TMP / "written.txt").exists(), "移动/改名", str(moved))
    outside_write = harness.call("files__write", path=str(Path.home() / ".." / "dsh-should-not-exist.txt"), content="x")
    harness.expect(outside_write.get("reasonCode") == "FILES_OUTSIDE_ROOT", "写入越界被拒绝", str(outside_write))
    harness.config["permission"] = "read_only"

    # 条数上限
    harness.config["max_files"] = 2
    limited = harness.call("files__list", path=str(TMP), limit=100)
    harness.expect(limited.get("count") <= 2, "条数上限生效", str(limited.get("count")))
    harness.config["file_limit_mode"] = "unlimited"
    harness.config["max_files"] = 50
    big = harness.call("files__list", path=str(TMP), limit=100)
    harness.expect(big.get("count") > 2, "不限条数时不再截断", str(big.get("count")))
    harness.config["file_limit_mode"] = "custom"
    harness.config["max_files"] = 50

    view = harness.runtime.settings_view()
    harness.expect(view["access_status"]["state"] == "ready", "设置页状态", str(view["access_status"]))
    harness.expect(view["permission"] == "read_only" and view["scope"] == "custom", "设置值回显")

    described = file_config.settings_descriptor()
    harness.expect(
        [field["key"] for field in described["fields"]]
        == ["scope", "custom_roots", "file_limit_mode", "max_files", "permission", "access_status"],
        "设置描述符字段",
        str([field["key"] for field in described["fields"]]),
    )

    # 目录范围预设
    home_cfg = file_config.build({"scope": "home"})
    harness.expect(home_cfg.roots and home_cfg.roots[0] == Path.home().resolve(), "范围=用户目录", str(home_cfg.roots))
    drives_cfg = file_config.build({"scope": "drives"})
    harness.expect(len(drives_cfg.roots) >= 1, "范围=全部磁盘可枚举", str(drives_cfg.describe_roots()))
    warn = file_config.status_value(file_config.build({"scope": "drives", "file_limit_mode": "unlimited", "permission": "full"}))
    harness.expect(warn["state"] == "warning" and "全部磁盘" in warn["message"], "高风险组合给出警告", str(warn))

    check_setup(harness)

    total = len(harness.failures)
    print()
    print(f"结果：{'全部通过' if total == 0 else str(total) + ' 项失败'}")
    shutil.rmtree(TMP, ignore_errors=True)
    return 0 if total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
