from typing import Any

from shared.text import normalize_text_lower
from modules.chat.shared.transcript import store_chat_message
from modules.chat.nlp import (
    detect_conversation_intent,
    extract_department_from_text,
    message_may_require_contact_intent,
)
from modules.chat.flows.contact.helpers.context import (
    _extract_flow_context,
    _resolve_chat_memory,
    _update_flow_context_from_intent,
)
from modules.chat.flows.contact.helpers.employees import _find_employee_candidates, _normalize_department_label
from modules.chat.flows.contact.stages.confirmation import handle_confirmation_stage
from modules.chat.flows.contact.stages.disambiguation import handle_disambiguation_stage
from modules.chat.flows.contact.stages.entry import handle_entry_stage
from modules.chat.flows.contact.stages.message_goal import handle_message_goal_stage
from modules.chat.flows.contact.stages.message_name import handle_message_name_stage
from modules.chat.flows.contact.constants import (
    AWAIT_CONFIRMATION,
    AWAIT_DISAMBIGUATION,
    AWAIT_MESSAGE_GOAL,
    AWAIT_MESSAGE_NAME,
    idle_state,
)
from modules.chat.flows.contact.replies.user import _classify_confirmation_reply, _resolve_contact_mode


_STAGE_HANDLERS: dict[str, Any] = {
    AWAIT_DISAMBIGUATION: handle_disambiguation_stage,
    AWAIT_CONFIRMATION: handle_confirmation_stage,
    AWAIT_MESSAGE_NAME: handle_message_name_stage,
    AWAIT_MESSAGE_GOAL: handle_message_goal_stage,
}


def _is_same_contact_target(active_flow_state: dict[str, Any], semantic_intent: dict[str, Any]) -> bool:
    target_type = str(semantic_intent.get("target_type") or "none").strip().lower()
    target_value = normalize_text_lower(str(semantic_intent.get("target_value") or ""))
    target_department = _normalize_department_label(str(semantic_intent.get("target_department") or ""))

    active_selected = active_flow_state.get("selected") if isinstance(active_flow_state, dict) else {}
    active_target_kind = str((active_flow_state or {}).get("target_kind") or "person").strip().lower()
    active_department = _normalize_department_label(str((active_flow_state or {}).get("department") or ""))
    active_name = normalize_text_lower(str((active_selected or {}).get("nama") or ""))
    active_selected_department = _normalize_department_label(str((active_selected or {}).get("departemen") or ""))

    if target_type == "department":
        return active_target_kind == "department" and bool(target_department) and active_department == target_department

    if target_type == "person":
        same_name = bool(target_value) and active_name == target_value
        if not target_department:
            return same_name
        return same_name and active_selected_department == target_department

    return False


def _should_restart_contact_flow(
    *,
    stage: str,
    user_message: str,
    active_flow_state: dict[str, Any],
    semantic_intent: dict[str, Any],
    semantic_contact_usable: bool,
) -> bool:
    if stage not in {
        AWAIT_DISAMBIGUATION,
        AWAIT_CONFIRMATION,
        AWAIT_MESSAGE_NAME,
        AWAIT_MESSAGE_GOAL,
    }:
        return False

    if not semantic_contact_usable:
        return False

    if _classify_confirmation_reply(user_message) != "unknown":
        return False

    return not _is_same_contact_target(active_flow_state, semantic_intent)


def _default_semantic_intent() -> dict[str, Any]:
    return {
        "intent": "unknown",
        "confidence": 0.0,
        "target_type": "none",
        "target_value": "",
        "target_department": "",
        "action": "none",
        "contact_mode": "auto",
        "search_phrase": "",
    }


def _should_detect_contact_intent(
    *,
    user_message: str,
    is_active_stage: bool,
    active_flow_state: dict[str, Any],
) -> bool:
    if not user_message:
        return False

    if not message_may_require_contact_intent(user_message, active_flow_state):
        return False

    if not is_active_stage:
        return True

    active_stage_allows_new_target = _classify_confirmation_reply(user_message) == "unknown"
    return active_stage_allows_new_target


def _is_contact_intent_usable(user_message: str, semantic_intent: dict[str, Any]) -> bool:
    semantic_target_type = str(semantic_intent.get("target_type") or "none").strip().lower()
    semantic_target_value = str(semantic_intent.get("target_value") or "").strip()
    semantic_action = str(semantic_intent.get("action") or "none").strip().lower()
    semantic_contact_detected = (
        str(semantic_intent.get("intent") or "").strip().lower() == "contact_employee"
    )

    if not (semantic_contact_detected and semantic_action == "contact"):
        return False

    semantic_contact_has_explicit_target = (
        semantic_target_type in {"person", "department"}
        and bool(semantic_target_value)
    )
    if semantic_contact_has_explicit_target:
        return True

    fallback_query = str(semantic_intent.get("search_phrase") or "").strip() or user_message
    fallback_matches = _find_employee_candidates(
        fallback_query,
        department_hint=str(semantic_intent.get("target_department") or "").strip() or extract_department_from_text(user_message) or "",
    )
    return bool(fallback_matches)


def handle_contact_flow(
    message: str,
    conversation_id: str | None = None,
    history: list[dict] | None = None,
    flow_state: dict[str, Any] | None = None,
) -> dict:
    resolved_conversation_id, prior_history = _resolve_chat_memory(conversation_id, history=history)
    user_message = (message or "").strip()
    safe_flow_state = flow_state if isinstance(flow_state, dict) else {}
    stage = str(safe_flow_state.get("stage") or "idle").strip().lower()
    is_active_stage = stage in _STAGE_HANDLERS
    base_context = _extract_flow_context(safe_flow_state)
    should_probe_intent_llm = _should_detect_contact_intent(
        user_message=user_message,
        is_active_stage=is_active_stage,
        active_flow_state=safe_flow_state,
    )
    semantic_intent = (
        detect_conversation_intent(
            user_message,
            flow_state=safe_flow_state,
            allow_llm=True,
        )
        if should_probe_intent_llm
        else _default_semantic_intent()
    )
    action = _resolve_contact_mode(semantic_intent, safe_flow_state, user_message)
    flow_context = _update_flow_context_from_intent(base_context, semantic_intent)

    if not user_message:
        return {
            "handled": False,
            "flow_state": idle_state(flow_context),
            "conversation_id": resolved_conversation_id,
            "history": prior_history,
        }

    semantic_contact_usable = _is_contact_intent_usable(user_message, semantic_intent)

    if _should_restart_contact_flow(
        stage=stage,
        user_message=user_message,
        active_flow_state=safe_flow_state,
        semantic_intent=semantic_intent,
        semantic_contact_usable=semantic_contact_usable,
    ):
        safe_flow_state = {}
        stage = "idle"
        is_active_stage = False

    if not is_active_stage and not semantic_contact_usable:
        return {
            "handled": False,
            "flow_state": idle_state(flow_context),
            "conversation_id": resolved_conversation_id,
            "history": prior_history,
        }

    store_chat_message(resolved_conversation_id, "user", user_message)

    ctx: dict[str, Any] = {
        "message": user_message,
        "conversation_id": resolved_conversation_id,
        "safe_flow_state": safe_flow_state,
        "flow_context": flow_context,
        "action": action,
        "semantic_intent": semantic_intent,
    }
    handler = _STAGE_HANDLERS.get(stage)
    if handler:
        return handler(ctx)
    return handle_entry_stage(ctx)
