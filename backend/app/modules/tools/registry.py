from __future__ import annotations

from importlib import import_module
from types import ModuleType


_TOOL_MODULES = {
    "employee_directory": "modules.tools.employee_directory.tool",
}


def get_tool(name: str) -> ModuleType:
    key = str(name or "").strip().lower()
    module_path = _TOOL_MODULES.get(key)
    if not module_path:
        raise KeyError(f"Unknown tool: {name}")
    return import_module(module_path)
