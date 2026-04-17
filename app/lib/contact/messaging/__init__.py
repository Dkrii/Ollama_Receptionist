from importlib import import_module
from typing import Any

__all__ = [
    "dispatch_contact_message",
    "get_active_messaging_provider",
    "is_contact_messaging_configured",
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    service = import_module("lib.contact.messaging.service")
    value = getattr(service, name)
    globals()[name] = value
    return value
