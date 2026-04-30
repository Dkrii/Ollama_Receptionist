import re
from typing import Any

from shared.utils.text import normalize_text_lower
from modules.chat.utils.slots import normalize_pending_action


CONTACT_AMBIGUITY_MORE_OPTIONS = "more_options"
CONTACT_AMBIGUITY_NEED_HELP = "need_help"
CONTACT_AMBIGUITY_REPEAT_OPTIONS = "repeat_options"
CONTACT_AMBIGUITY_UNKNOWN = "unknown"

_REPEAT_OPTION_PATTERNS = (
    r"\b(?:list|daftar|opsi|pilihan)\s+(?:lagi|tadi)\b",
    r"\b(?:ulang|ulangi|repeat)\b",
    r"\b(?:siapa|apa)\s+saja\s+tadi\b",
    r"\bsebutkan\s+lagi\b",
    r"\btampilkan\s+lagi\b",
)
_MORE_OPTION_PATTERNS = (
    r"\bada\s+lagi\b",
    r"\bada\s+(?:yang\s+)?lain\b",
    r"\byang\s+lain\b",
    r"\byang\s+lain\s+ada\b",
    r"\b(?:beri|kasih|cari|carikan|tampilkan)\b.+\blain\b",
    r"\b(?:opsi|pilihan)\s+lain\b",
    r"\bselain\s+itu\b",
    r"\blainnya\b",
)
_NEED_HELP_PATTERNS = (
    r"\bmaksudnya\b",
    r"\bbagaimana\s+(?:cara\s+)?pilih\b",
    r"\bgimana\s+(?:cara\s+)?pilih\b",
    r"\bpilih\s+yang\s+mana\b",
    r"\bnomor\s+berapa\b",
    r"\b(?:saya\s+)?bingung\b",
)


def _has_pending_candidates(pending_action: dict[str, Any] | None) -> bool:
    pending = normalize_pending_action(pending_action)
    candidates = pending.get("candidates") if pending else []
    return isinstance(candidates, list) and bool(candidates)


def _matches_any_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def classify_contact_ambiguity_reply(message: str, pending_action: dict[str, Any] | None) -> str:
    if not _has_pending_candidates(pending_action):
        return CONTACT_AMBIGUITY_UNKNOWN

    normalized = normalize_text_lower(message)
    if not normalized:
        return CONTACT_AMBIGUITY_UNKNOWN

    if _matches_any_pattern(normalized, _REPEAT_OPTION_PATTERNS):
        return CONTACT_AMBIGUITY_REPEAT_OPTIONS
    if _matches_any_pattern(normalized, _MORE_OPTION_PATTERNS):
        return CONTACT_AMBIGUITY_MORE_OPTIONS
    if _matches_any_pattern(normalized, _NEED_HELP_PATTERNS):
        return CONTACT_AMBIGUITY_NEED_HELP
    return CONTACT_AMBIGUITY_UNKNOWN
