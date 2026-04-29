from __future__ import annotations

import logging

from modules.tools.registry import get_tool


_logger = logging.getLogger(__name__)


def load_employee_directory() -> list[dict]:
    try:
        return list(get_tool("employee_directory").list_employees())
    except Exception:
        _logger.exception("contacts employee directory tool failed")
        return []
