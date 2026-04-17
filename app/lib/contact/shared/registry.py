from config import settings


_SUPPORTED_CALL_PROVIDERS = {"twilio"}
_SUPPORTED_MESSAGING_PROVIDERS = {"wablas"}


def get_contact_call_provider() -> str:
    provider = str(getattr(settings, "contact_call_provider", "") or "twilio").strip().lower()
    return provider or "twilio"


def get_contact_messaging_provider() -> str:
    provider = str(getattr(settings, "contact_messaging_provider", "") or "wablas").strip().lower()
    return provider or "wablas"


def is_supported_call_provider(provider: str) -> bool:
    return str(provider or "").strip().lower() in _SUPPORTED_CALL_PROVIDERS


def is_supported_messaging_provider(provider: str) -> bool:
    return str(provider or "").strip().lower() in _SUPPORTED_MESSAGING_PROVIDERS
