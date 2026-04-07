import re


SOCIAL_PHRASES = (
    "halo",
    "hai",
    "hi",
    "hello",
    "selamat pagi",
    "selamat siang",
    "selamat sore",
    "selamat malam",
    "pagi",
    "siang",
    "sore",
    "malam",
    "apa kabar",
    "terima kasih",
    "makasih",
    "thanks",
    "thank you",
    "dadah",
    "daah",
    "bye",
    "good bye",
    "sampai jumpa",
)

SOCIAL_TOKENS = {
    "halo",
    "hallo",
    "hai",
    "hi",
    "hello",
    "pagi",
    "siang",
    "sore",
    "malam",
    "thanks",
    "bye",
}


def _normalize_message(message: str) -> str:
    return " ".join((message or "").lower().split())


def _message_tokens(message: str) -> list[str]:
    normalized = _normalize_message(message)
    cleaned = re.sub(r"[^a-z0-9\s]", " ", normalized)
    return [token for token in cleaned.split() if token]


def is_social_message(message: str) -> bool:
    normalized = _normalize_message(message)
    if not normalized:
        return False

    if any(phrase in normalized for phrase in SOCIAL_PHRASES):
        return True

    tokens = _message_tokens(normalized)
    if not tokens:
        return False

    if len(tokens) <= 3 and all(token in SOCIAL_TOKENS for token in tokens):
        return True

    return False
