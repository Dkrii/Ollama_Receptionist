import logging
from typing import Any

from config import settings
from modules.chat.repository import ChatRepository

from .employees import _normalize_department_label


_logger = logging.getLogger(__name__)


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


def _resolve_chat_memory(
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


def _extract_flow_context(flow_state: dict[str, Any] | None) -> dict[str, str]:
    context = flow_state.get("context") if isinstance(flow_state, dict) else {}
    if not isinstance(context, dict):
        context = {}

    return {
        "last_topic_type": str(context.get("last_topic_type") or "none").strip().lower(),
        "last_topic_value": str(context.get("last_topic_value") or "").strip(),
        "last_intent": str(context.get("last_intent") or "unknown").strip().lower(),
    }


def _update_flow_context_from_intent(
    base_context: dict[str, str],
    intent_result: dict[str, Any],
) -> dict[str, str]:
    context = {
        "last_topic_type": str(base_context.get("last_topic_type") or "none"),
        "last_topic_value": str(base_context.get("last_topic_value") or ""),
        "last_intent": str(base_context.get("last_intent") or "unknown"),
    }

    intent = str(intent_result.get("intent") or "unknown").strip().lower()
    target_type = str(intent_result.get("target_type") or "none").strip().lower()
    target_value = str(intent_result.get("target_value") or "").strip()

    if intent in {"company_info", "contact_employee"} and target_type in {"department", "person"} and target_value:
        context["last_topic_type"] = target_type
        context["last_topic_value"] = _normalize_department_label(target_value) if target_type == "department" else target_value

    context["last_intent"] = intent
    return context
