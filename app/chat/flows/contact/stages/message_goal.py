import logging
from typing import Any

from chat.memory import store_chat_message
from chat.nlu import extract_visitor_goal
from chat.flows.contact.helper import (
    _build_contact_message_text,
    _build_stage,
    _extract_session,
    _unpack_ctx,
)
from chat.flows.contact.receptionist_replies import (
    _build_contact_response,
    _build_message_goal_follow_up,
    _build_message_name_follow_up,
    _build_notify_delivery_answer,
    _default_contact_delivery_detail,
    _expired_response,
)
from config import settings
from contacts import dispatch_contact_message
from storage.admin_repository import AdminRepository


_logger = logging.getLogger(__name__)


def handle_message_goal_stage(ctx: dict) -> dict:
    user_message, conversation_id, safe_flow_state, flow_context, action = _unpack_ctx(ctx)
    selected, target_kind, department = _extract_session(safe_flow_state)
    visitor_name = str(safe_flow_state.get("visitor_name") or "").strip()

    if not isinstance(selected, dict) or not selected.get("id"):
        return _expired_response(conversation_id, flow_context, "Sesi pesan berakhir. Silakan ulangi permintaan hubungi karyawan.")

    if not visitor_name:
        answer = "Mohon sebutkan nama Anda terlebih dahulu sebelum menyampaikan tujuan."
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage("await_message_name", flow_context, action=action, selected=selected, target_kind=target_kind, department=department),
            follow_up=_build_message_name_follow_up(selected),
        )

    visitor_goal = extract_visitor_goal(user_message, safe_flow_state)
    if len(visitor_goal) < 5:
        answer = "Tujuannya masih terlalu singkat. Mohon jelaskan tujuan Anda dengan lebih lengkap."
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage("await_message_goal", flow_context, action=action, selected=selected, target_kind=target_kind, department=department, visitor_name=visitor_name),
            follow_up=_build_message_goal_follow_up(selected),
        )

    stored_message: dict[str, Any] | None = None
    dispatch_result: dict[str, Any] | None = None
    initial_message_provider = str(getattr(settings, "contact_messaging_provider", "") or "wablas").strip().lower() or "wablas"
    message_content = _build_contact_message_text(selected, visitor_name, visitor_goal)
    try:
        stored_message = AdminRepository.create_contact_message(
            employee_id=int(selected["id"]),
            employee_nama=str(selected["nama"]),
            employee_departemen=str(selected["departemen"]),
            employee_nomor_wa=str(selected["nomor_wa"]),
            visitor_name=visitor_name,
            visitor_goal=visitor_goal,
            message_text=message_content,
            channel="whatsapp",
            delivery_status="queued",
            delivery_detail="Menunggu dispatcher WhatsApp.",
            delivery_provider=initial_message_provider,
        )
    except Exception:
        _logger.exception("chat.contact message record create failed")
        answer = "Maaf, pesan belum berhasil diproses. Silakan coba lagi beberapa saat."
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_build_stage("idle", flow_context))

    try:
        dispatch_result = dispatch_contact_message(
            employee=selected,
            visitor_name=visitor_name,
            visitor_goal=visitor_goal,
            message_text=message_content,
            message_id=int(stored_message["id"]),
        )
    except Exception as exc:
        _logger.exception("chat.contact message dispatch failed")
        try:
            AdminRepository.update_contact_message_delivery(
                message_id=int(stored_message["id"]),
                delivery_status="failed",
                delivery_detail="Dispatcher WhatsApp gagal dijalankan.",
                delivery_provider=initial_message_provider,
                provider_payload={
                    "error": "dispatch_failed",
                    "detail": str(exc),
                },
                mark_sent=False,
            )
        except Exception:
            _logger.exception("chat.contact message failure update failed")
        answer = "Maaf, pesan belum berhasil dikirim. Silakan coba lagi beberapa saat."
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_build_stage("idle", flow_context))

    try:
        dispatch_status = str(dispatch_result.get("status") or "").strip().lower()
        delivered_payload = AdminRepository.update_contact_message_delivery(
            message_id=int(stored_message["id"]),
            delivery_status=dispatch_status or "failed",
            delivery_detail=str(dispatch_result.get("detail") or _default_contact_delivery_detail(dispatch_status)),
            delivery_provider=str(dispatch_result.get("provider") or initial_message_provider),
            provider_message_id=str(dispatch_result.get("provider_message_id") or ""),
            provider_payload=dispatch_result.get("provider_payload"),
            mark_sent=dispatch_status in {"accepted", "sent"},
        )
    except Exception:
        _logger.exception("chat.contact message delivery update failed")
        dispatch_status = str(dispatch_result.get("status") or "").strip().lower()
        delivered_payload = {
            **(stored_message or {}),
            "delivery_status": dispatch_status or "failed",
            "delivery_detail": str(dispatch_result.get("detail") or _default_contact_delivery_detail(dispatch_status)),
            "delivery_provider": str(dispatch_result.get("provider") or initial_message_provider),
            "provider_message_id": str(dispatch_result.get("provider_message_id") or ""),
            "provider_payload": dispatch_result.get("provider_payload"),
        }

    delivery_status = str((delivered_payload or {}).get("delivery_status") or "").strip().lower()
    answer = _build_notify_delivery_answer(str(selected["nama"]), delivery_status)
    store_chat_message(conversation_id, "assistant", answer)
    return _build_contact_response(
        answer=answer,
        conversation_id=conversation_id,
        flow_state=_build_stage("idle", flow_context),
        action_result={
            "type": "notify",
            "status": delivery_status or "failed",
            "provider": str((delivered_payload or {}).get("delivery_provider") or initial_message_provider),
            "employee": {
                "id": selected["id"],
                "nama": selected["nama"],
                "departemen": selected["departemen"],
                "jabatan": selected["jabatan"],
            },
            "message": delivered_payload,
        },
    )
