import logging

from modules.chat.repository import ChatRepository


_logger = logging.getLogger(__name__)


def store_chat_message(conversation_id: str | None, role: str, content: str) -> None:
    if not conversation_id:
        return
    try:
        ChatRepository.add_message(conversation_id, role, content)
    except Exception:
        _logger.exception("chat.transcript write failed conversation_id=%s role=%s", conversation_id, role)
