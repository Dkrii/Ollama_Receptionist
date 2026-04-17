from typing import Any, TypedDict


class ContactMessageDispatchResult(TypedDict, total=False):
    provider: str
    status: str
    detail: str
    provider_message_id: str
    provider_payload: dict[str, Any] | list[Any] | str | None
