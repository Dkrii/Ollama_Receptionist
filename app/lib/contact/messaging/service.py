from lib.contact.messaging.providers import wablas
from lib.contact.messaging.types import ContactMessageDispatchResult
from lib.contact.shared.registry import get_contact_messaging_provider, is_supported_messaging_provider


def get_active_messaging_provider() -> str:
    return get_contact_messaging_provider()


def is_contact_messaging_configured() -> bool:
    provider = get_contact_messaging_provider()
    if provider == wablas.MESSAGING_PROVIDER_WABLAS:
        return wablas.is_configured()
    return False


def dispatch_contact_message(
    *,
    employee: dict,
    visitor_name: str,
    visitor_goal: str,
    message_text: str,
    message_id: int | None = None,
) -> ContactMessageDispatchResult:
    provider = get_contact_messaging_provider()
    if provider == wablas.MESSAGING_PROVIDER_WABLAS:
        return wablas.dispatch_message(
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
