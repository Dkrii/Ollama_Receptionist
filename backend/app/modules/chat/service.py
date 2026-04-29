from typing import Any

from modules.chat.constants import (
    DECISION_ANSWER_KNOWLEDGE,
    DECISION_CANCEL_PENDING_ACTION,
    DECISION_CONFIRM_NO,
    DECISION_CONFIRM_YES,
    DECISION_CONTINUE_PENDING_ACTION,
    DECISION_START_CONTACT_MESSAGE,
)
from modules.chat.providers.contact_message_provider import (
    cancel_contact_message,
    continue_contact_message,
    handle_contact_message_turn,
)
from modules.chat.providers.decision_provider import decide_next_action
from modules.chat.providers.knowledge_provider import answer_knowledge_stream
from modules.chat.utils.memory import resolve_chat_memory
from modules.chat.utils.slots import build_flow_state, normalize_pending_action
from modules.chat.utils.streaming import static_chat_events
from modules.chat.utils.transcript import store_chat_message


class ChatAppService:
    @staticmethod
    def ask_stream(
        message: str,
        conversation_id: str | None = None,
        history: list[dict] | None = None,
        flow_state: dict[str, Any] | None = None,
    ):
        resolved_conversation_id, prior_history = resolve_chat_memory(conversation_id, history=history)
        user_message = (message or "").strip()
        pending_action = normalize_pending_action(
            (flow_state or {}).get("pending_action") if isinstance(flow_state, dict) else None
        )

        decision = decide_next_action(
            user_message,
            pending_action=pending_action,
            history=prior_history,
        )
        intent = str(decision.get("intent") or DECISION_ANSWER_KNOWLEDGE).strip().lower()

        if pending_action and intent == DECISION_CANCEL_PENDING_ACTION:
            answer = cancel_contact_message(pending_action)
            store_chat_message(resolved_conversation_id, "user", user_message)
            store_chat_message(resolved_conversation_id, "assistant", answer)
            return static_chat_events(
                answer=answer,
                conversation_id=resolved_conversation_id,
                flow_state=build_flow_state(None),
                route="contact_message",
            )

        if pending_action and intent == DECISION_CONTINUE_PENDING_ACTION:
            answer, next_pending = continue_contact_message(pending_action)
            store_chat_message(resolved_conversation_id, "user", user_message)
            store_chat_message(resolved_conversation_id, "assistant", answer)
            return static_chat_events(
                answer=answer,
                conversation_id=resolved_conversation_id,
                flow_state=build_flow_state(next_pending),
                route="contact_message",
            )

        should_handle_contact = (
            intent == DECISION_START_CONTACT_MESSAGE
            or (pending_action is not None and intent in {DECISION_CONFIRM_YES, DECISION_CONFIRM_NO})
            or (pending_action is not None and intent not in {DECISION_ANSWER_KNOWLEDGE})
        )
        if should_handle_contact:
            contact_pending = None if intent == DECISION_START_CONTACT_MESSAGE else pending_action
            answer, next_pending = handle_contact_message_turn(
                user_message,
                pending_action=contact_pending,
                decision=decision,
            )
            store_chat_message(resolved_conversation_id, "user", user_message)
            store_chat_message(resolved_conversation_id, "assistant", answer)
            return static_chat_events(
                answer=answer,
                conversation_id=resolved_conversation_id,
                flow_state=build_flow_state(next_pending),
                route="contact_message",
            )

        return answer_knowledge_stream(
            user_message,
            conversation_id=resolved_conversation_id,
            history=prior_history,
            flow_state=build_flow_state(pending_action),
        )
