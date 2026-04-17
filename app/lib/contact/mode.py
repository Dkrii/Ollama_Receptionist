def normalize_contact_mode(value: str | None) -> str:
    mode = str(value or "").strip().lower()
    if mode in {"call", "notify"}:
        return mode
    return "call"
