import logging
from typing import Any

from fastapi import Request

from api.admin.repository import AdminRepository
from lib.contact.call import (
    ACTIVE_CALL_STATUSES,
    build_contact_call_status_detail,
    create_contact_call_session,
    issue_contact_call_access_token,
    mask_contact_value,
    parse_contact_call_status_payload,
    render_contact_call_twiml,
)

_logger = logging.getLogger(__name__)


class ContactCallService:
    @staticmethod
    def _request_id(request: Request | None) -> str:
        return str(getattr(getattr(request, "state", None), "request_id", "") or "-").strip()

    @staticmethod
    async def _resolve_call_session_id(
        request: Request,
        fallback_session_id: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        form = await request.form()
        payload = {key: value for key, value in form.multi_items()}
        resolved_session_id = str(
            fallback_session_id
            or payload.get("call_session_id")
            or request.query_params.get("call_session_id")
            or ""
        ).strip()
        if not resolved_session_id:
            raise RuntimeError("call_session_id wajib dikirim.")
        return resolved_session_id, payload

    @staticmethod
    def create_session_for_employee(employee: dict[str, Any]) -> dict[str, Any]:
        employee_name = str(employee.get("nama") or "karyawan")
        employee_phone = str(employee.get("nomor_wa") or "")
        session_result = create_contact_call_session(employee)

        return AdminRepository.create_contact_call(
            employee_id=int(employee["id"]),
            employee_nama=employee_name,
            employee_departemen=str(employee.get("departemen") or ""),
            employee_nomor_wa=employee_phone,
            call_status=str(session_result.get("status") or "failed"),
            call_detail=str(session_result.get("detail") or "Tidak terhubung."),
            call_provider=str(session_result.get("provider") or "dummy"),
            provider_payload=session_result.get("provider_payload"),
            call_session_id=str(session_result.get("session_id") or ""),
            dev_identity=str(session_result.get("dev_identity") or ""),
            provider_call_id=str(session_result.get("provider_call_id") or "").strip() or None,
            failure_reason=str(session_result.get("failure_reason") or "").strip() or None,
        )

    @staticmethod
    def issue_access_token(call_session_id: str, request: Request | None = None) -> dict[str, Any]:
        stored_call = AdminRepository.get_contact_call_by_session_id(call_session_id)
        if not stored_call:
            raise RuntimeError("Sesi telepon tidak ditemukan.")

        token_payload = issue_contact_call_access_token(
            provider=str(stored_call.get("call_provider") or ""),
            identity=str(stored_call.get("dev_identity") or ""),
            call_session_id=call_session_id,
        )
        _logger.info(
            "contact.call.token id=%s session=%s provider=%s",
            ContactCallService._request_id(request),
            mask_contact_value(str(stored_call.get("call_session_id") or ""), head=6, tail=4),
            str(token_payload.get("provider") or stored_call.get("call_provider") or "-"),
        )
        return token_payload

    @staticmethod
    def get_status(call_session_id: str) -> dict[str, Any]:
        stored_call = AdminRepository.get_contact_call_by_session_id(call_session_id)
        if not stored_call:
            raise RuntimeError("Sesi telepon tidak ditemukan.")
        return stored_call

    @staticmethod
    def fail_from_client(
        call_session_id: str,
        *,
        status: str = "failed",
        reason: str = "client_error",
        request: Request | None = None,
    ) -> dict[str, Any]:
        stored_call = AdminRepository.get_contact_call_by_session_id(call_session_id)
        if not stored_call:
            raise RuntimeError("Sesi telepon tidak ditemukan.")

        normalized_status = str(status or "failed").strip().lower()
        if normalized_status not in {"failed", "busy", "no_response"}:
            normalized_status = "failed"

        current_status = str(stored_call.get("call_status") or "").strip().lower()
        if current_status and current_status not in ACTIVE_CALL_STATUSES:
            return stored_call

        updated = AdminRepository.update_contact_call_status(
            call_id=int(stored_call["id"]),
            call_status=normalized_status,
            call_detail=build_contact_call_status_detail(
                provider=str(stored_call.get("call_provider") or ""),
                employee_name=str(stored_call.get("employee_nama") or "karyawan"),
                status=normalized_status,
            ),
            call_provider=str(stored_call.get("call_provider") or "dummy"),
            provider_call_id=str(
                stored_call.get("provider_call_id")
                or stored_call.get("twilio_call_sid")
                or ""
            ).strip() or None,
            twilio_call_sid=str(stored_call.get("twilio_call_sid") or "").strip() or None,
            provider_payload={
                "source": "dev_client",
                "reason": str(reason or "client_error").strip().lower(),
            },
            failure_reason=str(reason or "client_error").strip().lower(),
            mark_ended=True,
        )
        _logger.info(
            "contact.call.fail id=%s session=%s status=%s reason=%s",
            ContactCallService._request_id(request),
            mask_contact_value(call_session_id, head=6, tail=4),
            normalized_status,
            str(reason or "client_error").strip().lower() or "-",
        )
        return updated or stored_call

    @staticmethod
    async def render_twiml(call_session_id: str | None, request: Request) -> str:
        call_session_id, payload = await ContactCallService._resolve_call_session_id(request, call_session_id)
        stored_call = AdminRepository.get_contact_call_by_session_id(call_session_id)
        if not stored_call:
            raise RuntimeError("Sesi telepon tidak ditemukan.")

        provider = str(stored_call.get("call_provider") or "").strip().lower()
        provider_call_id = str(payload.get("CallSid") or "").strip()

        AdminRepository.update_contact_call_status(
            call_id=int(stored_call["id"]),
            call_status="dialing_employee",
            call_detail=build_contact_call_status_detail(
                provider=provider,
                employee_name=str(stored_call.get("employee_nama") or "karyawan"),
                status="dialing_employee",
            ),
            call_provider=provider or "dummy",
            provider_call_id=provider_call_id or None,
            twilio_call_sid=provider_call_id or None if provider == "twilio" else None,
            provider_payload=payload,
        )

        _logger.info(
            "contact.call.twiml id=%s session=%s sid=%s employee=%s",
            ContactCallService._request_id(request),
            mask_contact_value(call_session_id, head=6, tail=4),
            mask_contact_value(provider_call_id),
            str(stored_call.get("employee_nama") or "-"),
        )

        return render_contact_call_twiml(
            provider=provider,
            call_session_id=call_session_id,
            employee_phone=str(stored_call.get("employee_nomor_wa") or ""),
        )

    @staticmethod
    async def sync_status(call_session_id: str | None, request: Request) -> dict[str, Any]:
        call_session_id, payload = await ContactCallService._resolve_call_session_id(request, call_session_id)
        stored_call = AdminRepository.get_contact_call_by_session_id(call_session_id)
        if not stored_call:
            raise RuntimeError("Sesi telepon tidak ditemukan.")

        provider = str(stored_call.get("call_provider") or "").strip().lower()
        status_update = parse_contact_call_status_payload(
            provider=provider,
            payload=payload,
            employee_name=str(stored_call.get("employee_nama") or "karyawan"),
        )

        updated = AdminRepository.update_contact_call_status(
            call_id=int(stored_call["id"]),
            call_status=str(status_update.get("status") or "failed"),
            call_detail=str(status_update.get("detail") or "Tidak terhubung."),
            call_provider=provider or "dummy",
            provider_call_id=str(status_update.get("provider_call_id") or "").strip() or None,
            twilio_call_sid=(
                str(status_update.get("provider_call_id") or "").strip() or None
                if provider == "twilio"
                else None
            ),
            provider_payload=status_update.get("provider_payload"),
            failure_reason=str(status_update.get("failure_reason") or "").strip() or None,
            mark_connected=bool(status_update.get("mark_connected")),
            mark_ended=bool(status_update.get("mark_ended")),
        )
        _logger.info(
            "contact.call.status id=%s session=%s sid=%s status=%s raw=%s",
            ContactCallService._request_id(request),
            mask_contact_value(call_session_id, head=6, tail=4),
            mask_contact_value(str(status_update.get("provider_call_id") or "")),
            str(status_update.get("status") or "failed"),
            str(payload.get("DialCallStatus") or payload.get("CallStatus") or "").strip() or "-",
        )
        return updated or stored_call
