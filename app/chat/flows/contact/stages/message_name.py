from chat.memory import store_chat_message
from chat.nlu import extract_visitor_name
from chat.flows.contact.helper import _build_stage, _extract_session, _unpack_ctx
from chat.flows.contact.receptionist_replies import (
    _build_contact_response,
    _build_message_goal_follow_up,
    _build_message_name_follow_up,
    _expired_response,
)


def handle_message_name_stage(ctx: dict) -> dict:
    user_message, conversation_id, safe_flow_state, flow_context, action = _unpack_ctx(ctx)
    selected, target_kind, department = _extract_session(safe_flow_state)

    if not isinstance(selected, dict) or not selected.get("id"):
        return _expired_response(conversation_id, flow_context, "Sesi pesan berakhir. Silakan ulangi permintaan hubungi karyawan.")

    visitor_name = extract_visitor_name(user_message, safe_flow_state)
    if not visitor_name:
        answer = "Mohon sebutkan nama Anda terlebih dahulu agar saya bisa mencatat pesannya."
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage("await_message_name", flow_context, action=action, selected=selected, target_kind=target_kind, department=department),
            follow_up=_build_message_name_follow_up(selected),
        )

    answer = f"Terima kasih, {visitor_name}. Sekarang mohon sampaikan tujuan atau keperluan Anda."
    store_chat_message(conversation_id, "assistant", answer)
    return _build_contact_response(
        answer=answer,
        conversation_id=conversation_id,
        flow_state=_build_stage("await_message_goal", flow_context, action=action, selected=selected, target_kind=target_kind, department=department, visitor_name=visitor_name),
        follow_up=_build_message_goal_follow_up(selected),
    )
