def normalize_contact_mode(value: str | None) -> str:
    mode = str(value or "auto").strip().lower()
    if mode in {"call", "notify", "auto"}:
        return mode
    return "auto"
