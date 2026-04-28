import logging

from storage.chat_repository import ChatRepository


_logger = logging.getLogger(__name__)


def normalize_text(value: str) -> str:
    return " ".join((value or "").lower().split())


def store_chat_message(conversation_id: str | None, role: str, content: str) -> None:
    if not conversation_id:
        return
    try:
        ChatRepository.add_message(conversation_id, role, content)
    except Exception:
        _logger.exception("chat.memory write failed conversation_id=%s role=%s", conversation_id, role)
