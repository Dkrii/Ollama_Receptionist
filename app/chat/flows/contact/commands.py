import re


CANCEL_PATTERNS = (
    r"\bbatal\b",
    r"\bgak jadi\b",
    r"\bga jadi\b",
    r"\bnggak jadi\b",
    r"\btidak jadi\b",
    r"\btidak usah\b",
    r"\bga usah\b",
    r"\bnggak usah\b",
)


def looks_like_cancel(message: str) -> bool:
    text = " ".join((message or "").lower().split())
    return bool(text and any(re.search(pattern, text) for pattern in CANCEL_PATTERNS))
