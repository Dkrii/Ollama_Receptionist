from config import settings


def normalize_contact_mode(value: str | None) -> str:
    mode = str(value or "").strip().lower()
    if mode in {"call", "notify"}:
        return mode

    default_mode = str(getattr(settings, "contact_default_mode", "notify") or "notify").strip().lower()
    return default_mode if default_mode in {"call", "notify"} else "notify"
