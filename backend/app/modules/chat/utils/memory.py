import logging
import re

from config import settings
from shared.utils.text import normalize_text, normalize_text_lower
from modules.chat.repository import ChatRepository


_logger = logging.getLogger(__name__)

_CONTACT_ASSISTANT_PATTERNS = (
    r"^apakah anda ingin menghubungi ",
    r"^tentu, apakah anda ingin saya menghubungkan anda dengan tim ",
    r"^baik, bagaimana jika ",
    r"^silakan jawab terlebih dahulu, apakah anda ingin melanjutkan hubungi ",
    r"^saya menemukan beberapa nama yang mungkin anda maksud",
    r"^mohon sebutkan nama anda terlebih dahulu",
    r"^terima kasih, .+ sekarang mohon sampaikan tujuan atau keperluan anda",
    r"^tujuannya masih terlalu singkat",
)


def _is_contact_prompt_boilerplate(role: str, content: str) -> bool:
    if str(role or "").strip().lower() != "assistant":
        return False

    normalized = normalize_text_lower(content)
    if not normalized:
        return False

    return any(re.search(pattern, normalized) for pattern in _CONTACT_ASSISTANT_PATTERNS)


def filter_model_history(history: list[dict] | None) -> list[dict]:
    if not history:
        return []

    filtered: list[dict] = []
    for item in history:
        role = str(item.get("role") or "").strip().lower()
        content = normalize_text(str(item.get("content") or ""))
        if not role or not content:
            continue
        if _is_contact_prompt_boilerplate(role, content):
            continue

        next_item = {"role": role, "content": content}
        created_at = str(item.get("created_at") or "").strip()
        if created_at:
            next_item["created_at"] = created_at
        filtered.append(next_item)

    return filtered


def _trim_history(history: list[dict] | None) -> list[dict]:
    if not history:
        return []

    trimmed_history: list[dict] = []
    for item in history[-settings.chat_recent_turns:]:
        role = str(item.get("role", "")).strip()
        content = str(item.get("content", "")).strip()
        if not role or not content:
            continue
        trimmed_history.append({"role": role, "content": content})
    return trimmed_history


def resolve_chat_memory(
    conversation_id: str | None,
    history: list[dict] | None = None,
) -> tuple[str | None, list[dict]]:
    fallback_history = _trim_history(history)
    try:
        resolved_conversation_id = ChatRepository.resolve_conversation(conversation_id)
        prior_history = ChatRepository.get_recent_turns(resolved_conversation_id)
        if not prior_history and not conversation_id:
            prior_history = fallback_history
        return resolved_conversation_id, prior_history
    except Exception:
        _logger.exception("chat.memory unavailable conversation_id=%s", conversation_id)
        return None, fallback_history
