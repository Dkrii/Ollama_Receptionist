from config import settings
from lib.contact.call.providers import telnyx, twilio
from lib.contact.messaging.providers import wablas


CALL_PROVIDER_REGISTRY = {
    twilio.CALL_PROVIDER_TWILIO: twilio,
    telnyx.CALL_PROVIDER_TELNYX: telnyx,
}

MESSAGING_PROVIDER_REGISTRY = {
    wablas.MESSAGING_PROVIDER_WABLAS: wablas,
}


def get_contact_call_provider() -> str:
    provider = str(getattr(settings, "contact_call_provider", "") or "twilio").strip().lower()
    return provider or "twilio"


def get_contact_messaging_provider() -> str:
    provider = str(getattr(settings, "contact_messaging_provider", "") or "wablas").strip().lower()
    return provider or "wablas"


def get_contact_call_provider_adapter(provider: str | None = None):
    return CALL_PROVIDER_REGISTRY.get(str(provider or get_contact_call_provider()).strip().lower())


def get_contact_messaging_provider_adapter(provider: str | None = None):
    return MESSAGING_PROVIDER_REGISTRY.get(str(provider or get_contact_messaging_provider()).strip().lower())


def is_supported_call_provider(provider: str) -> bool:
    return str(provider or "").strip().lower() in CALL_PROVIDER_REGISTRY


def is_supported_messaging_provider(provider: str) -> bool:
    return str(provider or "").strip().lower() in MESSAGING_PROVIDER_REGISTRY
