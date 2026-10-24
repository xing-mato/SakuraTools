"""统一的错误类型：带稳定原因码，交给 Agent 时不会泄漏本机细节。"""

from __future__ import annotations


class FilesError(RuntimeError):
    """插件内的可预期错误；code 会作为 reasonCode 回给模型。"""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code

    def to_result(self) -> dict[str, object]:
        return {"isError": True, "reasonCode": self.code, "error": self.message}
