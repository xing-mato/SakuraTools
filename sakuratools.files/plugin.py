"""本地文件插件入口（Plugin API v4）。

只读设计：
- 只用 open("rb") / scandir / stat 访问用户文件；
- 唯一的写操作是宿主的 Artifacts 服务，把图片字节复制进宿主工件目录，
  好让本轮对话把图交给视觉模型 —— 等同于用户手动发一张截图。
"""

from __future__ import annotations

import threading
from typing import Any

try:
    from .files_core import config as file_config
    from .files_core import handlers
except ImportError:  # 作为顶层模块加载时（entry: plugin:FilesPlugin）
    from files_core import config as file_config
    from files_core import handlers

TOOL_GROUP = "plugin"


class FilesPlugin:
    def __init__(self) -> None:
        self._runtime: handlers.Runtime | None = None
        self._lock = threading.RLock()
        self._closed = False

    def setup(self, context: Any) -> None:
        self.context = context
        logger = context.get("sakura.host.logging")
        try:
            artifacts = context.get("sakura.host.artifacts")
        except Exception:  # noqa: BLE001 - 没有工件服务时退化为只读元信息
            artifacts = None
        self._runtime = handlers.Runtime(context.config.get, logger, artifacts)
        context.effect(self.close)

        tools = context.get("sakura.host.tools")
        for tool in handlers.TOOLS:
            tools.register(
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["inputSchema"],
                    "group": TOOL_GROUP,
                    "risk": tool["risk"],
                },
                self._handler(tool["name"]),
            )

        if logger is not None:
            try:
                logger.info("SakuraTools 已就绪", fields={"tools": len(handlers.TOOLS)})
            except Exception:  # noqa: BLE001
                pass

        settings = context.get("sakura.host.settings")
        settings.register(
            file_config.settings_descriptor(),
            load=self.load,
            save=self.save,
            actions={"check_access": self.check_access},
        )

    # ---- 设置页 ----

    def load(self) -> dict[str, Any]:
        runtime = self._runtime
        if runtime is None:
            return {}
        return runtime.settings_view()

    def save(self, values: dict[str, Any]) -> None:
        runtime = self._runtime
        if runtime is None:
            return
        self.context.config.update(runtime.normalize_settings(values))

    def check_access(self, values: dict[str, Any]) -> dict[str, Any]:
        """按当前表单值即时校验目录，返回状态字段。"""

        candidate = file_config.build(file_config.normalize(values))
        return {"access_status": file_config.status_value(candidate)}

    # ---- 工具 ----

    def _handler(self, name: str):
        def execute(arguments: dict[str, Any]) -> dict[str, Any]:
            runtime = self._runtime
            if runtime is None or self._closed:
                return {"isError": True, "reasonCode": "FILES_NOT_READY", "error": "插件尚未就绪"}
            return runtime.call(name, arguments)

        return execute

    def close(self) -> None:
        with self._lock:
            self._closed = True
