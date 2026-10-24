"""工具实现：浏览 / 读取 / 看图 / 检索，以及完全权限下的写入。

默认只读：写入类工具在 permission=read_only 时直接拒绝。
图片通过宿主的 Artifacts 服务送进本轮对话，等同于用户手动截图。
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import re
from pathlib import Path
from typing import Any, Callable, Mapping

from . import config as file_config
from . import documents, images, policy, textio
from .errors import FilesError

# 遍历与检索的兜底上限，防止“全部磁盘 + 不限”把一次调用拖死。
MAX_SCAN_ENTRIES = 20000
MAX_GREP_SCANNED = 5000
MAX_GREP_BYTES = 2 * 1024 * 1024
MAX_WRITE_BYTES = 2 * 1024 * 1024
SKIP_DIRS = {
    "$recycle.bin", "__pycache__", "node_modules", "site-packages", "system volume information", "windows",
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "files__list",
        "risk": "low",
        "description": (
            "列出目录内容（只读）。用于了解某个文件夹里有什么、确认文件是否存在。"
            "返回名称、类型、大小和修改时间；目录在前。要读内容请用 files__read。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目录路径；留空表示当前允许范围的根目录。"},
                "pattern": {"type": "string", "description": "文件名通配符，例如 *.md；留空为全部。"},
                "recursive": {"type": "boolean", "description": "是否递归列出子目录，默认 false。"},
                "limit": {"type": "integer", "description": "最多返回多少条；上限由插件设置决定。"},
            },
            "required": [],
        },
    },
    {
        "name": "files__read",
        "risk": "medium",
        "description": (
            "读取一个文件的正文（只读）。纯文本、代码、日志按行返回并带行号；"
            "docx/xlsx/pptx/odt/epub/html/rtf/pdf 会先抽取正文。"
            "图片请改用 files__read_image，那样你能真正看到画面。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径。"},
                "start_line": {"type": "integer", "description": "从第几行开始，默认 1。"},
                "max_lines": {"type": "integer", "description": "最多返回多少行。"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "files__read_image",
        "risk": "medium",
        "description": (
            "读取本机的一张图片并放进本轮对话，使你真正看到画面内容"
            "（等同于用户手动截图发给你）。支持 png/jpeg/webp/gif。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图片文件路径。"},
                "note": {"type": "string", "description": "可选，一句想告诉用户的话。"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "files__stat",
        "risk": "low",
        "description": "查看文件或目录属性（只读）：类型、大小、修改时间；图片额外给出像素尺寸。",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "文件或目录路径。"}},
            "required": ["path"],
        },
    },
    {
        "name": "files__find",
        "risk": "low",
        "description": "按文件名在允许范围内查找（只读）。适合“我桌面上那个报告在哪”这类问题。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "description": "搜索起点；留空表示允许范围的根目录。"},
                "pattern": {"type": "string", "description": "文件名通配符，例如 *.pdf；默认 *。"},
                "max_depth": {"type": "integer", "description": "最多向下几层，默认 4，最大 8。"},
                "limit": {"type": "integer", "description": "最多返回多少条；上限由插件设置决定。"},
            },
            "required": [],
        },
    },
    {
        "name": "files__grep",
        "risk": "medium",
        "description": "在允许范围内的文本文件里搜索一段文字（只读），返回文件、行号与那一行。适合在笔记或代码里找关键词。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "description": "搜索起点；留空表示允许范围的根目录。"},
                "query": {"type": "string", "description": "要查找的文字。"},
                "file_pattern": {"type": "string", "description": "只搜这些文件名，例如 *.md。"},
                "regex": {"type": "boolean", "description": "把 query 当正则表达式，默认 false。"},
                "case_sensitive": {"type": "boolean", "description": "区分大小写，默认 false。"},
                "max_hits": {"type": "integer", "description": "最多返回多少条命中。"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "files__write",
        "risk": "high",
        "description": (
            "写入文本文件（需要“完全权限”）。mode=overwrite 覆盖，append 追加。"
            "只读模式下会被拒绝；写之前确认路径正确，覆盖会丢失原内容。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目标文件路径。"},
                "content": {"type": "string", "description": "要写入的文本内容。"},
                "mode": {"type": "string", "enum": ["overwrite", "append"], "description": "默认 overwrite。"},
                "create_parents": {"type": "boolean", "description": "父目录不存在时是否创建，默认 false。"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "files__mkdir",
        "risk": "high",
        "description": "新建目录（需要“完全权限”）。已存在则直接返回。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目录路径。"},
                "parents": {"type": "boolean", "description": "是否创建多级父目录，默认 true。"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "files__move",
        "risk": "high",
        "description": "移动或重命名文件/目录（需要“完全权限”）。不覆盖已存在的目标，除非 overwrite=true。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "源路径。"},
                "destination": {"type": "string", "description": "目标路径。"},
                "overwrite": {"type": "boolean", "description": "目标已存在时是否覆盖，默认 false。"},
            },
            "required": ["source", "destination"],
        },
    },
]


def _iso(timestamp: float) -> str:
    import datetime

    return datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def _entry(path: Path) -> dict[str, Any]:
    try:
        info = path.stat()
    except OSError:
        return {"name": path.name, "path": str(path), "type": "unreadable"}
    is_dir = path.is_dir()
    item: dict[str, Any] = {
        "name": path.name + ("\\" if is_dir else ""),
        "path": str(path),
        "type": "dir" if is_dir else "file",
        "size": "" if is_dir else _human_size(info.st_size),
        "modified": _iso(info.st_mtime),
    }
    if not is_dir and documents.kind_for(path) == "image":
        try:
            meta = images.sniff(images.read_header(path, 65536))
            if meta["width"]:
                item["image"] = f"{meta['width']}x{meta['height']}"
        except OSError:
            pass
    return item


class Runtime:
    """把宿主服务包在一个无状态运行时里；每次调用重新读配置。"""

    def __init__(
        self,
        config_get: Callable[[], Mapping[str, Any]] | None = None,
        logger: Any = None,
        artifacts: Any = None,
    ) -> None:
        self._config_get = config_get or (lambda: {})
        self._logger = logger
        self._artifacts = artifacts

    # ---- 配置 ----

    def _raw(self) -> Mapping[str, Any]:
        try:
            value = self._config_get()
        except Exception:  # noqa: BLE001 - 配置读取失败时退回默认值
            return {}
        return value if isinstance(value, Mapping) else {}

    def config(self) -> file_config.FileConfig:
        return file_config.build(self._raw())

    def settings_view(self) -> dict[str, Any]:
        config = self.config()
        return {
            "scope": config.scope,
            "custom_roots": config.custom_roots,
            "file_limit_mode": "unlimited" if config.max_files is None else "custom",
            "max_files": config.max_files or file_config.DEFAULT_MAX_FILES,
            "permission": config.permission,
            "access_status": file_config.status_value(config),
        }

    def normalize_settings(self, values: Mapping[str, Any] | None) -> dict[str, Any]:
        return file_config.normalize(values)

    def _warn(self, message: str, **fields: Any) -> None:
        logger = self._logger
        if logger is None:
            return
        try:
            logger.warning(message, fields=fields)
        except Exception:  # noqa: BLE001
            pass

    # ---- 分发 ----

    def call(self, name: str, arguments: Mapping[str, Any] | None) -> dict[str, Any]:
        handler = getattr(self, "_tool_" + name.split("__", 1)[-1], None)
        if handler is None:
            return {"isError": True, "reasonCode": "FILES_UNKNOWN_TOOL", "error": f"未知工具 {name}"}
        try:
            return handler(dict(arguments or {}))
        except FilesError as error:
            self._warn("文件工具返回错误", tool=name, reason_code=error.code)
            return error.to_result()
        except PermissionError:
            self._warn("文件工具权限不足", tool=name, reason_code="FILES_PERMISSION")
            return {"isError": True, "reasonCode": "FILES_PERMISSION", "error": "没有权限访问该路径"}
        except OSError as error:
            self._warn("文件工具 IO 失败", tool=name, reason_code="FILES_IO_ERROR")
            return {"isError": True, "reasonCode": "FILES_IO_ERROR", "error": str(error)}
        except Exception as error:  # noqa: BLE001
            self._warn("文件工具异常", tool=name, reason_code="FILES_INTERNAL", error_type=type(error).__name__)
            return {"isError": True, "reasonCode": "FILES_INTERNAL", "error": f"执行失败（{type(error).__name__}）"}

    # ---- 辅助 ----

    def _limit(self, config: file_config.FileConfig, requested: object) -> int:
        cap = config.limit
        try:
            value = int(requested)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return min(50, cap)
        return max(1, min(cap, value))

    def _default_root(self, config: file_config.FileConfig) -> Path:
        if not config.roots:
            raise FilesError("FILES_NO_ROOT", "还没有可读目录，请先在插件设置里选择可访问范围")
        return config.roots[0]

    @staticmethod
    def _require_write(config: file_config.FileConfig) -> None:
        if config.read_only:
            raise FilesError(
                "FILES_READ_ONLY",
                "当前是只读模式。需要写入的话，请让用户在 设置 → 插件 → 本地文件 里把“写入权限”改成完全权限。",
            )

    # ---- 只读工具 ----

    def _tool_list(self, args: Mapping[str, Any]) -> dict[str, Any]:
        config = self.config()
        target = policy.resolve(str(args.get("path") or ""), config) if args.get("path") else self._default_root(config)
        if not target.is_dir():
            raise FilesError("FILES_NOT_DIRECTORY", f"{target} 不是目录")
        pattern = str(args.get("pattern") or "").strip()
        recursive = bool(args.get("recursive", False))
        limit = self._limit(config, args.get("limit"))

        entries: list[dict[str, Any]] = []
        truncated = False
        scanned = 0
        stack: list[tuple[Path, int]] = [(target, 0)]
        while stack and len(entries) < limit and scanned < MAX_SCAN_ENTRIES:
            current, depth = stack.pop()
            try:
                children = sorted(current.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
            except PermissionError:
                continue
            for child in children:
                if len(entries) >= limit:
                    truncated = True
                    break
                scanned += 1
                if scanned > MAX_SCAN_ENTRIES:
                    truncated = True
                    break
                try:
                    if policy.deny_reason(child):
                        continue
                    if pattern and not fnmatch.fnmatch(child.name.casefold(), pattern.casefold()):
                        continue
                except OSError:
                    continue
                entries.append(_entry(child))
                if recursive and child.is_dir() and depth < 4:
                    stack.append((child, depth + 1))
        note = "只读；可用 files__read 或 files__read_image 继续读取具体文件。"
        if not entries and pattern:
            note = f"当前目录没有匹配 {pattern} 的条目；可设 recursive=true，或用 files__find 搜索整个范围。"
        return {"path": str(target), "count": len(entries), "entries": entries, "truncated": truncated, "note": note}

    def _tool_read(self, args: Mapping[str, Any]) -> dict[str, Any]:
        config = self.config()
        path = policy.resolve(str(args.get("path") or ""), config)
        if path.is_dir():
            raise FilesError("FILES_NOT_FILE", f"{path} 是目录，请用 files__list")
        if documents.kind_for(path) == "image":
            return {
                "isError": True,
                "reasonCode": "FILES_IS_IMAGE",
                "error": "这是图片，请改用 files__read_image 才能看到画面（files__read 只返回文本）。",
            }
        if documents.kind_for(path) == "document":
            result = documents.extract_document(path, max_chars=file_config.MAX_RETURN_CHARS)
            result["path"] = str(path)
            result["size"] = _human_size(path.stat().st_size)
            return result
        result = textio.read_text_file(
            path,
            max_bytes=file_config.MAX_FILE_BYTES,
            max_chars=file_config.MAX_RETURN_CHARS,
            start_line=int(args.get("start_line") or 1),
            max_lines=int(args.get("max_lines") or 0),
        )
        result["size"] = _human_size(path.stat().st_size)
        return result

    def _tool_read_image(self, args: Mapping[str, Any]) -> dict[str, Any]:
        config = self.config()
        path = policy.resolve(str(args.get("path") or ""), config)
        if path.is_dir():
            raise FilesError("FILES_NOT_FILE", f"{path} 是目录")
        size = path.stat().st_size
        if size > file_config.MAX_FILE_BYTES:
            raise FilesError("FILES_TOO_LARGE", f"图片 {_human_size(size)} 超过 {_human_size(file_config.MAX_FILE_BYTES)}")
        meta = images.sniff(images.read_header(path))
        if not meta["format"]:
            raise FilesError("FILES_NOT_IMAGE", "这不是受支持的图片格式（png/jpeg/webp/gif）")
        summary = f"已读取图片：{path.name}（{meta['width']}x{meta['height']}，{meta['mediaType']}，{_human_size(size)}）"
        note = str(args.get("note") or "").strip()
        if note:
            summary = f"{summary}。{note}"

        if meta["format"] not in images.ARTIFACT_MEDIA or self._artifacts is None:
            return {
                "path": str(path),
                "mediaType": meta["mediaType"],
                "width": meta["width"],
                "height": meta["height"],
                "content": summary,
                "note": "本次只返回了元信息，画面没有进入对话。",
            }

        allocation: Mapping[str, Any] | None = None
        try:
            allocation = self._artifacts.allocate(
                {"mediaType": meta["mediaType"], "suffix": "." + ("jpg" if meta["format"] == "jpeg" else meta["format"])}
            )
            target = Path(str(allocation["path"]))
            with path.open("rb") as reader, target.open("wb") as writer:
                for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                    writer.write(chunk)
            descriptor = self._artifacts.commit(str(allocation["artifactId"]))
        except Exception as error:  # noqa: BLE001
            if allocation is not None:
                try:
                    self._artifacts.release(str(allocation["artifactId"]))
                except Exception:  # noqa: BLE001
                    pass
            self._warn("图片工件创建失败", reason_code="FILES_ARTIFACT_FAILED", error_type=type(error).__name__)
            raise FilesError("FILES_ARTIFACT_FAILED", "图片暂时无法送入对话，稍后再试一次") from error

        # 宿主要求信封恰好是 {"content", "artifact"}，多一个键就会退化成普通 JSON。
        return {"content": summary, "artifact": descriptor}

    def _tool_stat(self, args: Mapping[str, Any]) -> dict[str, Any]:
        config = self.config()
        path = policy.resolve(str(args.get("path") or ""), config)
        info = path.stat()
        result: dict[str, Any] = {
            "path": str(path),
            "type": "dir" if path.is_dir() else "file",
            "size": _human_size(info.st_size),
            "sizeBytes": info.st_size,
            "modified": _iso(info.st_mtime),
            "created": _iso(info.st_ctime),
            "kind": documents.kind_for(path),
        }
        if path.is_file():
            if result["kind"] == "image":
                meta = images.sniff(images.read_header(path))
                result.update({"format": meta["format"], "width": meta["width"], "height": meta["height"]})
            if info.st_size <= 8 * 1024 * 1024:
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                result["sha256"] = digest.hexdigest()
        return result

    def _tool_find(self, args: Mapping[str, Any]) -> dict[str, Any]:
        config = self.config()
        root = policy.resolve(str(args.get("root") or ""), config) if args.get("root") else self._default_root(config)
        if not root.is_dir():
            raise FilesError("FILES_NOT_DIRECTORY", f"{root} 不是目录")
        pattern = str(args.get("pattern") or "*").strip() or "*"
        depth_limit = min(8, max(1, int(args.get("max_depth") or 4)))
        limit = self._limit(config, args.get("limit"))

        matches: list[dict[str, Any]] = []
        scanned = 0
        stack: list[tuple[Path, int]] = [(root, 0)]
        while stack and len(matches) < limit and scanned < MAX_SCAN_ENTRIES:
            current, depth = stack.pop()
            try:
                children = list(current.iterdir())
            except (PermissionError, OSError):
                continue
            for child in children:
                scanned += 1
                if scanned > MAX_SCAN_ENTRIES or len(matches) >= limit:
                    break
                name = child.name.casefold()
                if name in SKIP_DIRS:
                    continue
                try:
                    if policy.deny_reason(child):
                        continue
                    if child.is_dir():
                        if depth < depth_limit:
                            stack.append((child, depth + 1))
                        continue
                except OSError:
                    continue
                if fnmatch.fnmatch(name, pattern.casefold()):
                    matches.append(_entry(child))
        matches.sort(key=lambda item: item.get("modified", ""), reverse=True)
        return {"root": str(root), "pattern": pattern, "count": len(matches), "matches": matches,
                "note": "已达到文件数上限并停止；可缩小范围或调大上限继续找。" if len(matches) >= limit else ""}

    def _tool_grep(self, args: Mapping[str, Any]) -> dict[str, Any]:
        config = self.config()
        root = policy.resolve(str(args.get("root") or ""), config) if args.get("root") else self._default_root(config)
        if not root.is_dir():
            raise FilesError("FILES_NOT_DIRECTORY", f"{root} 不是目录")
        query = str(args.get("query") or "")
        if not query.strip():
            raise FilesError("FILES_INVALID_ARGUMENT", "query 不能为空")
        use_regex = bool(args.get("regex", False))
        case_sensitive = bool(args.get("case_sensitive", False))
        file_pattern = str(args.get("file_pattern") or "").strip()
        limit = self._limit(config, args.get("max_hits"))
        scanned_cap = min(MAX_GREP_SCANNED, max(64, limit * 4))
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            matcher = re.compile(query if use_regex else re.escape(query), flags)
        except re.error as error:
            raise FilesError("FILES_INVALID_ARGUMENT", f"正则表达式无效：{error}") from error

        hits: list[dict[str, Any]] = []
        scanned = 0
        stack: list[Path] = [root]
        while stack and len(hits) < limit and scanned < scanned_cap:
            current = stack.pop()
            try:
                children = list(current.iterdir())
            except (PermissionError, OSError):
                continue
            for child in children:
                if len(hits) >= limit or scanned >= scanned_cap:
                    break
                name = child.name.casefold()
                if name in SKIP_DIRS:
                    continue
                try:
                    if policy.deny_reason(child):
                        continue
                    if child.is_dir():
                        stack.append(child)
                        continue
                    if file_pattern and not fnmatch.fnmatch(name, file_pattern.casefold()):
                        continue
                    if documents.kind_for(child) != "text":
                        continue
                    if child.stat().st_size > MAX_GREP_BYTES:
                        continue
                except OSError:
                    continue
                scanned += 1
                try:
                    raw = child.read_bytes()
                except OSError:
                    continue
                from .decode import decode_text, looks_binary

                if looks_binary(raw[:8192]):
                    continue
                text, _encoding = decode_text(raw)
                for number, line in enumerate(text.splitlines(), start=1):
                    if matcher.search(line):
                        hits.append({"path": str(child), "line": number, "text": line.strip()[:240]})
                        if len(hits) >= limit:
                            break
        return {"root": str(root), "query": query, "scannedFiles": scanned, "count": len(hits), "hits": hits}

    # ---- 写入工具（完全权限） ----

    def _tool_write(self, args: Mapping[str, Any]) -> dict[str, Any]:
        config = self.config()
        self._require_write(config)
        path = policy.resolve_new(str(args.get("path") or ""), config)
        if path.is_dir():
            raise FilesError("FILES_IS_DIRECTORY", f"{path} 是目录")
        content = args.get("content")
        if not isinstance(content, str):
            raise FilesError("FILES_INVALID_ARGUMENT", "content 必须是字符串")
        raw = content.encode("utf-8")
        if len(raw) > MAX_WRITE_BYTES:
            raise FilesError("FILES_TOO_LARGE", f"单次写入超过 {MAX_WRITE_BYTES // 1024 // 1024} MB")
        if not path.parent.is_dir():
            if not bool(args.get("create_parents", False)):
                raise FilesError("FILES_NOT_FOUND", f"父目录不存在：{path.parent}")
            path.parent.mkdir(parents=True, exist_ok=True)
        mode = str(args.get("mode") or "overwrite").lower()
        if mode not in {"overwrite", "append"}:
            raise FilesError("FILES_INVALID_ARGUMENT", "mode 只能是 overwrite 或 append")
        existed = path.exists()
        with path.open("ab" if mode == "append" else "wb") as handle:
            handle.write(raw)
        self._warn("文件工具写入了文件", path=str(path), mode=mode, bytes=len(raw))
        return {"path": str(path), "mode": mode, "bytes": len(raw), "created": not existed}

    def _tool_mkdir(self, args: Mapping[str, Any]) -> dict[str, Any]:
        config = self.config()
        self._require_write(config)
        path = policy.resolve_new(str(args.get("path") or ""), config)
        existed = path.is_dir()
        if not existed:
            parents = bool(args.get("parents", True))
            if parents:
                path.mkdir(parents=True, exist_ok=True)
            else:
                if not path.parent.is_dir():
                    raise FilesError("FILES_NOT_FOUND", f"父目录不存在：{path.parent}")
                path.mkdir()
            self._warn("文件工具新建了目录", path=str(path))
        return {"path": str(path), "created": not existed}

    def _tool_move(self, args: Mapping[str, Any]) -> dict[str, Any]:
        config = self.config()
        self._require_write(config)
        source = policy.resolve(str(args.get("source") or ""), config)
        destination = policy.resolve_new(str(args.get("destination") or ""), config)
        overwrite = bool(args.get("overwrite", False))
        if destination.exists():
            if not overwrite:
                raise FilesError("FILES_EXISTS", f"目标已存在：{destination}（确认覆盖请传 overwrite=true）")
            if destination.is_dir():
                raise FilesError("FILES_IS_DIRECTORY", "目标目录已存在，不支持覆盖目录")
            destination.unlink()
        if not destination.parent.is_dir():
            raise FilesError("FILES_NOT_FOUND", f"目标目录不存在：{destination.parent}")
        import shutil

        shutil.move(str(source), str(destination))
        self._warn("文件工具移动了路径", source=str(source), destination=str(destination))
        return {"source": str(source), "destination": str(destination), "moved": True}
