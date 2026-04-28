import json
from typing import Any

from chat.flows.contact.flow import handle_contact_flow
from chat.flows.qa import ask_stream as ask_rag_stream


class ChatAppService:
    @staticmethod
    def ask_stream(
        message: str,
        conversation_id: str | None = None,
        history: list[dict] | None = None,
        flow_state: dict[str, Any] | None = None,
    ):
        contact_result = handle_contact_flow(
            message,
            conversation_id=conversation_id,
            history=history,
            flow_state=flow_state,
        )
        if contact_result.get("handled"):
            handled_answer = str(contact_result.get("answer") or "").strip()
            handled_conversation_id = contact_result.get("conversation_id")
            handled_flow_state = contact_result.get("flow_state") or {"stage": "idle"}
            handled_action = contact_result.get("action")
            handled_follow_up = contact_result.get("follow_up")

            def _contact_events():
                meta_payload = {
                    "type": "meta",
                    "route": "contact_flow",
                    "flow_state": handled_flow_state,
                }
                if handled_conversation_id:
                    meta_payload["conversation_id"] = handled_conversation_id
                yield json.dumps(meta_payload, ensure_ascii=False) + "\n"
                if handled_action:
                    yield json.dumps({"type": "action", "value": handled_action}, ensure_ascii=False) + "\n"
                if handled_answer:
                    yield json.dumps({"type": "token", "value": handled_answer}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "citations", "value": []}, ensure_ascii=False) + "\n"
                if handled_follow_up:
                    yield json.dumps({"type": "follow_up", "value": handled_follow_up}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"

            return _contact_events()

        return ask_rag_stream(
            message,
            conversation_id=contact_result.get("conversation_id"),
            history=contact_result.get("history") or [],
            flow_state=contact_result.get("flow_state") or {"stage": "idle"},
        )
