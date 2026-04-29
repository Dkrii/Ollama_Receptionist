from config import settings
from infrastructure import wablas


MESSAGING_PROVIDER_REGISTRY = {
    wablas.MESSAGING_PROVIDER_WABLAS: wablas,
}


def get_contact_messaging_provider() -> str:
    provider = str(getattr(settings, "contact_messaging_provider", "") or "wablas").strip().lower()
    return provider or "wablas"


def get_contact_messaging_provider_adapter(provider: str | None = None):
    return MESSAGING_PROVIDER_REGISTRY.get(str(provider or get_contact_messaging_provider()).strip().lower())


def is_supported_messaging_provider(provider: str) -> bool:
    return str(provider or "").strip().lower() in MESSAGING_PROVIDER_REGISTRY
