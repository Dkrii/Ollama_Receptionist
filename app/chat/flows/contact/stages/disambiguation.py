from chat.memory import store_chat_message
from chat.flows.contact.helper import (
    _build_stage,
    _format_employee_contact_target,
    _resolve_disambiguation_selection,
    _unpack_ctx,
)
from chat.flows.contact.receptionist_replies import (
    _build_cancel_contact_answer,
    _build_confirmation_follow_up,
    _build_contact_response,
    _build_disambiguation_follow_up,
    _build_disambiguation_prompt,
    _expired_response,
)
from chat.flows.contact.user_replies import _classify_confirmation_reply


def handle_disambiguation_stage(ctx: dict) -> dict:
    user_message, conversation_id, safe_flow_state, flow_context, action = _unpack_ctx(ctx)

    candidates = safe_flow_state.get("candidates") or []
    if not isinstance(candidates, list) or not candidates:
        return _expired_response(conversation_id, flow_context, "Pilihan kandidat sudah kedaluwarsa. Silakan sebutkan lagi siapa karyawan yang ingin dihubungi.")

    if _classify_confirmation_reply(user_message) == "confirm_no":
        answer = _build_cancel_contact_answer(None, "person", "")
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage("idle", flow_context),
        )

    selected = _resolve_disambiguation_selection(user_message, candidates)
    if not selected:
        if len(candidates) == 1 and isinstance(candidates[0], dict) and candidates[0].get("id"):
            selected = candidates[0]
            answer = f"Apakah Anda ingin menghubungi {_format_employee_contact_target(selected)}?"
            store_chat_message(conversation_id, "assistant", answer)
            return _build_contact_response(
                answer=answer,
                conversation_id=conversation_id,
                flow_state=_build_stage("await_confirmation", flow_context, action=action, selected=selected),
                follow_up=_build_confirmation_follow_up(selected, target_kind="person"),
            )

        answer = _build_disambiguation_prompt(candidates, "Saya menemukan beberapa nama yang mungkin Anda maksud.")
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage("await_disambiguation", flow_context, action=action, candidates=candidates),
            follow_up=_build_disambiguation_follow_up(candidates),
        )

    answer = f"Apakah Anda ingin menghubungi {_format_employee_contact_target(selected)}?"
    store_chat_message(conversation_id, "assistant", answer)
    return _build_contact_response(
        answer=answer,
        conversation_id=conversation_id,
        flow_state=_build_stage("await_confirmation", flow_context, action=action, selected=selected),
        follow_up=_build_confirmation_follow_up(selected, target_kind="person"),
    )
