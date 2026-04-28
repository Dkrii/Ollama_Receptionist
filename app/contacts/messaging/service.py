from contacts.messaging.types import ContactMessageDispatchResult
from contacts.registry import (
    get_contact_messaging_provider,
    get_contact_messaging_provider_adapter,
    is_supported_messaging_provider,
)


def dispatch_contact_message(
    *,
    employee: dict,
    visitor_name: str,
    visitor_goal: str,
    message_text: str,
    message_id: int | None = None,
) -> ContactMessageDispatchResult:
    provider = get_contact_messaging_provider()
    adapter = get_contact_messaging_provider_adapter(provider)
    if adapter is not None:
        return adapter.dispatch_message(
            employee=employee,
            visitor_name=visitor_name,
            visitor_goal=visitor_goal,
            message_text=message_text,
            message_id=message_id,
        )

    if not is_supported_messaging_provider(provider):
        return {
            "provider": provider,
            "status": "failed",
            "detail": f"Provider messaging '{provider}' belum didukung.",
            "provider_message_id": "",
            "provider_payload": {"error": "unsupported_messaging_provider"},
        }

    return {
        "provider": provider,
        "status": "failed",
        "detail": "Provider messaging gagal di-resolve.",
        "provider_message_id": "",
        "provider_payload": {"error": "messaging_provider_resolution_failed"},
    }
