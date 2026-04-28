import logging

from modules.chat.shared.transcript import store_chat_message
from modules.chat.flows.contact.helpers.actions import _start_contact_request
from modules.chat.flows.contact.helpers.employees import (
    _find_department_candidates,
    _format_employee_contact_target,
)
from modules.chat.flows.contact.helpers.payloads import (
    _build_stage,
    _extract_session,
    _unpack_ctx,
)
from modules.chat.flows.contact.replies.receptionist import (
    _build_call_unavailable_message_answer,
    _build_cancel_contact_answer,
    _build_confirmation_follow_up,
    _build_contact_request_success_answer,
    _build_contact_response,
    _build_disambiguation_follow_up,
    _build_disambiguation_prompt,
    _build_message_name_follow_up,
    _expired_response,
    _is_successful_contact_status,
    _is_unavailable_contact_status,
)
from modules.chat.flows.contact.replies.user import _classify_confirmation_reply


_logger = logging.getLogger(__name__)


def handle_confirmation_stage(ctx: dict) -> dict:
    user_message, conversation_id, safe_flow_state, flow_context, action = _unpack_ctx(ctx)
    selected, target_kind, department = _extract_session(safe_flow_state)
    candidates = safe_flow_state.get("candidates") or []

    if target_kind == "department" and (not isinstance(selected, dict) or not selected.get("id")):
        if isinstance(candidates, list) and candidates:
            selected = candidates[0]
        elif department:
            dept_matches = _find_department_candidates(department)
            selected = dept_matches[0] if dept_matches else {}

    if not isinstance(selected, dict) or not selected.get("id"):
        return _expired_response(conversation_id, flow_context, "Sesi konfirmasi sudah berakhir. Silakan ulangi permintaan hubungi karyawan.")

    current_intent = _classify_confirmation_reply(user_message)
    if current_intent == "confirm_no":
        if target_kind == "person" and isinstance(candidates, list) and len(candidates) > 1:
            remaining_candidates = [
                item for item in candidates
                if str(item.get("id") or "") != str(selected.get("id") or "")
            ]
            if remaining_candidates:
                if len(remaining_candidates) == 1 and isinstance(remaining_candidates[0], dict) and remaining_candidates[0].get("id"):
                    fallback_selected = remaining_candidates[0]
                    answer = f"Baik, bagaimana jika {_format_employee_contact_target(fallback_selected)}?"
                    store_chat_message(conversation_id, "assistant", answer)
                    return _build_contact_response(
                        answer=answer,
                        conversation_id=conversation_id,
                        flow_state=_build_stage(
                            "await_confirmation", flow_context,
                            action=action,
                            selected=fallback_selected,
                            target_kind="person",
                            candidates=remaining_candidates,
                        ),
                        follow_up=_build_confirmation_follow_up(
                            fallback_selected,
                            target_kind="person",
                        ),
                    )

                answer = _build_disambiguation_prompt(remaining_candidates, "Baik, saya carikan nama lain yang mungkin sesuai.")
                store_chat_message(conversation_id, "assistant", answer)
                return _build_contact_response(
                    answer=answer,
                    conversation_id=conversation_id,
                    flow_state=_build_stage("await_disambiguation", flow_context, action=action, candidates=remaining_candidates),
                    follow_up=_build_disambiguation_follow_up(remaining_candidates),
                )

        answer = _build_cancel_contact_answer(selected, target_kind, department)
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_build_stage("idle", flow_context))

    if current_intent != "confirm_yes":
        answer = (
            "Silakan jawab terlebih dahulu, apakah Anda ingin melanjutkan hubungi "
            f"{selected['nama']} ({selected['departemen']})?"
        )
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage("await_confirmation", flow_context, action=action, selected=selected, target_kind=target_kind, department=department, candidates=candidates),
            follow_up=_build_confirmation_follow_up(selected, target_kind=target_kind, department=department),
        )

    try:
        action_result = _start_contact_request(selected, action)
    except Exception:
        _logger.exception("chat.contact action dispatch failed")
        answer = "Maaf, sistem belum berhasil memproses permintaan hubungi saat ini."
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_build_stage("idle", flow_context))

    if action == "call" and isinstance(action_result, dict):
        action_result["fallback_flow_state"] = _build_stage(
            "await_message_name",
            flow_context,
            action=action,
            selected=selected,
            target_kind=target_kind,
            department=department,
        )
        action_result["fallback_answer"] = _build_call_unavailable_message_answer(selected)
        action_result["fallback_follow_up"] = _build_message_name_follow_up(selected)

    request_status = str(action_result.get("status") or "").strip().lower()

    if action == "notify":
        answer = (
            f"Baik, saya bantu sampaikan pesan untuk {selected['nama']}. "
            "Mohon sebutkan nama Anda terlebih dahulu."
        )
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage(
                "await_message_name",
                flow_context,
                action=action,
                selected=selected,
                target_kind=target_kind,
                department=department,
            ),
            follow_up=_build_message_name_follow_up(selected),
            action_result=action_result,
        )

    if _is_unavailable_contact_status(request_status):
        answer = _build_call_unavailable_message_answer(selected)
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage(
                "await_message_name",
                flow_context,
                action=action,
                selected=selected,
                target_kind=target_kind,
                department=department,
            ),
            follow_up=_build_message_name_follow_up(selected),
        )

    if _is_successful_contact_status(request_status):
        answer = _build_contact_request_success_answer(selected, action_result)
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage("idle", flow_context),
            action_result=action_result,
        )

    answer = "Permintaan hubungi belum berhasil diproses. Silakan coba lagi beberapa saat."
    store_chat_message(conversation_id, "assistant", answer)
    return _build_contact_response(
        answer=answer,
        conversation_id=conversation_id,
        flow_state=_build_stage("idle", flow_context),
        action_result=action_result,
    )
