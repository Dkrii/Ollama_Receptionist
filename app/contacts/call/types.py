from typing import Any, TypedDict


class ContactCallResult(TypedDict, total=False):
    provider: str
    status: str
    detail: str
    session_id: str
    provider_call_id: str
    provider_payload: dict[str, Any] | list[Any] | str | None
    dev_identity: str
    failure_reason: str


class ContactCallStatusUpdate(TypedDict, total=False):
    status: str
    detail: str
    provider_call_id: str
    provider_payload: dict[str, Any] | list[Any] | str | None
    failure_reason: str
    mark_connected: bool
    mark_ended: bool
