"""Call provider facade used by contact workflows."""

from importlib import import_module
from typing import Any

__all__ = [
    "ACTIVE_CALL_STATUSES",
    "build_contact_call_status_detail",
    "create_contact_call_session",
    "issue_contact_call_access_token",
    "mask_contact_value",
    "parse_contact_call_client_status_payload",
    "parse_contact_call_status_payload",
    "render_contact_call_twiml",
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    service = import_module("contacts.call.service")
    value = getattr(service, name)
    globals()[name] = value
    return value
