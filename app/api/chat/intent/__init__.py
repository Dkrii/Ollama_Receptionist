"""Intent parsing for chat.

This package groups intent detection + text extraction helpers used primarily by the
contact flow.

Public API is re-exported here so callers can keep importing from `api.chat.intent`.
"""

from .department import KNOWN_DEPARTMENTS, extract_department_from_text, normalize_department
from .detect import detect_conversation_intent, message_may_require_contact_intent
from .extract import extract_visitor_goal, extract_visitor_name

__all__ = [
    "KNOWN_DEPARTMENTS",
    "normalize_department",
    "extract_department_from_text",
    "message_may_require_contact_intent",
    "detect_conversation_intent",
    "extract_visitor_name",
    "extract_visitor_goal",
]
