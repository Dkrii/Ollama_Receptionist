import re
from typing import Any

from modules.chat.nlp import normalize_contact_mode
from common.text import normalize_text_lower


_YES_PATTERNS = (
    r"\bya\b",
    r"\biya\b",
    r"\byes\b",
    r"\bok(?:e)?\b",
    r"\bsetuju\b",
    r"\bbetul\b",
    r"\blanjut\b",
    r"\bboleh\b",
    r"\bsilakan\b",
)
_NO_PATTERNS = (
    r"\btidak\b",
    r"\bnggak\b",
    r"\bga\b",
    r"\bgak\b",
    r"\bno\b",
    r"\bbatal\b",
    r"\bjangan\b",
    r"\btidak jadi\b",
    r"\bga usah\b",
    r"\bnggak usah\b",
)
_LEAVE_MESSAGE_PATTERNS = (
    r"\btinggal(?:kan)? pesan\b",
    r"\btitip pesan\b",
    r"\bpesan saja\b",
    r"\bleave message\b",
)
_EXPLICIT_NOTIFY_PATTERNS = _LEAVE_MESSAGE_PATTERNS + (
    r"\bwhatsapp\b",
    r"\bwa\b",
    r"\bkirim(?:kan)? pesan\b",
    r"\bchat\b",
)


def _matches_any_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _classify_confirmation_reply(message: str) -> str:
    normalized = normalize_text_lower(message)
    if not normalized:
        return "unknown"

    has_yes = _matches_any_pattern(normalized, _YES_PATTERNS)
    has_no = _matches_any_pattern(normalized, _NO_PATTERNS)

    if has_yes and not has_no:
        return "confirm_yes"
    if has_no and not has_yes:
        return "confirm_no"
    return "unknown"


def _is_explicit_notify_request(message: str) -> bool:
    normalized = normalize_text_lower(message)
    if not normalized:
        return False
    return any(re.search(pattern, normalized) for pattern in _EXPLICIT_NOTIFY_PATTERNS)


def _resolve_contact_mode(
    intent_result: dict[str, Any],
    flow_state: dict[str, Any] | None = None,
    user_message: str = "",
) -> str:
    intent_mode = normalize_contact_mode(intent_result.get("contact_mode"))
    if intent_mode == "notify" and _is_explicit_notify_request(user_message):
        return "notify"

    if isinstance(flow_state, dict):
        saved = str(flow_state.get("action") or "").strip().lower()
        if saved == "notify":
            return saved
    return "notify"
