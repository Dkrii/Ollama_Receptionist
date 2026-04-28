def normalize_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def normalize_text_lower(value: str) -> str:
    return normalize_text(value).lower()
