from chat.memory import store_chat_message
from chat.nlu import extract_department_from_text
from chat.flows.contact.helper import (
    _build_stage,
    _find_department_candidates,
    _find_employee_candidates,
    _format_employee_contact_target,
    _normalize_department_label,
    _unpack_ctx,
)
from chat.flows.contact.receptionist_replies import (
    _build_confirmation_follow_up,
    _build_contact_response,
    _build_disambiguation_follow_up,
    _build_disambiguation_prompt,
)


def handle_entry_stage(ctx: dict) -> dict:
    user_message, conversation_id, _, flow_context, action = _unpack_ctx(ctx)
    semantic_intent: dict = ctx["semantic_intent"]

    semantic_target_type = str(semantic_intent.get("target_type") or "none").strip().lower()
    semantic_target_value = str(semantic_intent.get("target_value") or "").strip()
    department_target = ""

    if semantic_target_type == "department" and semantic_target_value:
        department_target = _normalize_department_label(semantic_target_value)

    if department_target:
        dept_matches = _find_department_candidates(department_target)
        if not dept_matches:
            answer = f"Saat ini saya belum menemukan staf terdaftar di tim {department_target}."
            store_chat_message(conversation_id, "assistant", answer)
            return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_build_stage("idle", flow_context))

        selected = dept_matches[0]
        answer = f"Tentu, apakah Anda ingin saya menghubungkan Anda dengan tim {department_target}?"
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage("await_confirmation", flow_context, action=action, target_kind="department", department=department_target, selected=selected, candidates=dept_matches[:5]),
            follow_up=_build_confirmation_follow_up(selected, target_kind="department", department=department_target),
        )

    if semantic_target_type == "person" and semantic_target_value:
        search_query = semantic_target_value
    else:
        search_query = str(semantic_intent.get("search_phrase") or "").strip() or user_message
    department_hint = (
        str(semantic_intent.get("target_department") or "").strip()
        or extract_department_from_text(user_message)
        or ""
    )
    matches = _find_employee_candidates(search_query, department_hint=department_hint)

    if not matches:
        answer = "Saya tidak menemukan karyawan tersebut. Silakan sebutkan nama lengkap atau divisinya."
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_build_stage("idle", flow_context))

    if len(matches) == 1:
        selected = matches[0]
        answer = f"Apakah Anda ingin menghubungi {_format_employee_contact_target(selected)}?"
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage("await_confirmation", flow_context, action=action, selected=selected, target_kind="person"),
            follow_up=_build_confirmation_follow_up(selected, target_kind="person"),
        )

    candidates = matches
    answer = _build_disambiguation_prompt(candidates, "Saya menemukan beberapa nama yang mungkin Anda maksud.")
    store_chat_message(conversation_id, "assistant", answer)
    return _build_contact_response(
        answer=answer,
        conversation_id=conversation_id,
        flow_state=_build_stage("await_disambiguation", flow_context, action=action, candidates=candidates),
        follow_up=_build_disambiguation_follow_up(candidates),
    )
