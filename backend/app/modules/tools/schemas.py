from __future__ import annotations

from typing import Any, TypedDict


class ToolResult(TypedDict, total=False):
    ok: bool
    data: Any
    error: str
    source: str
