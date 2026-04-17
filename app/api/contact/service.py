import logging
from typing import Any

from fastapi import Request

from api.admin.repository import AdminRepository
from config import settings
from lib.contact.call_session import (
    ACTIVE_CALL_STATUSES,
    build_dev_identity,
    build_status_detail,
    build_twiml,
    call_provider,
    create_access_token,
    create_call_session_id,
    mask_value,
    normalize_twilio_call_status,
    require_employee_phone,
    require_twilio_settings,
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
        provider = call_provider()
        employee_name = str(employee.get("nama") or "karyawan")
        employee_phone = str(employee.get("nomor_wa") or "")
        call_session_id = create_call_session_id()
        dev_identity = build_dev_identity(call_session_id)

        failure_reason = ""
        initial_status = "preparing"
        initial_detail = build_status_detail(employee_name=employee_name, status="preparing")
        provider_payload: dict[str, Any] = {
            "app_env": str(getattr(settings, "app_env", "") or "").strip().lower(),
            "channel": "two_way_call",
        }

        try:
            require_employee_phone(employee)
            require_twilio_settings()
        except Exception as exc:
            failure_reason = str(exc)
            initial_status = "failed"
            initial_detail = build_status_detail(employee_name=employee_name, status="failed")
            provider_payload["setup_error"] = failure_reason

        return AdminRepository.create_contact_call(
            employee_id=int(employee["id"]),
            employee_nama=employee_name,
            employee_departemen=str(employee.get("departemen") or ""),
            employee_nomor_wa=employee_phone,
            call_status=initial_status,
            call_detail=initial_detail,
            call_provider=provider,
            provider_payload=provider_payload,
            call_session_id=call_session_id,
            dev_identity=dev_identity,
            failure_reason=failure_reason or None,
        )

    @staticmethod
    def issue_access_token(call_session_id: str, request: Request | None = None) -> dict[str, Any]:
        stored_call = AdminRepository.get_contact_call_by_session_id(call_session_id)
        if not stored_call:
            raise RuntimeError("Sesi telepon tidak ditemukan.")

        token = create_access_token(identity=str(stored_call.get("dev_identity") or ""))
        _logger.info(
            "contact.call.token id=%s session=%s provider=%s",
            ContactCallService._request_id(request),
            mask_value(str(stored_call.get("call_session_id") or ""), head=6, tail=4),
            str(stored_call.get("call_provider") or call_provider()),
        )
        return {
            "provider": str(stored_call.get("call_provider") or call_provider()),
            "token": token,
            "identity": str(stored_call.get("dev_identity") or ""),
            "call_session_id": call_session_id,
        }

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
            call_detail=build_status_detail(
                employee_name=str(stored_call.get("employee_nama") or "karyawan"),
                status=normalized_status,
            ),
            call_provider=str(stored_call.get("call_provider") or call_provider()),
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
            mask_value(call_session_id, head=6, tail=4),
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

        twilio_call_sid = str(payload.get("CallSid") or "").strip()

        AdminRepository.update_contact_call_status(
            call_id=int(stored_call["id"]),
            call_status="dialing_employee",
            call_detail=build_status_detail(
                employee_name=str(stored_call.get("employee_nama") or "karyawan"),
                status="dialing_employee",
            ),
            call_provider=str(stored_call.get("call_provider") or call_provider()),
            provider_call_id=twilio_call_sid,
            twilio_call_sid=twilio_call_sid,
            provider_payload=payload,
        )

        _logger.info(
            "contact.call.twiml id=%s session=%s sid=%s employee=%s",
            ContactCallService._request_id(request),
            mask_value(call_session_id, head=6, tail=4),
            mask_value(twilio_call_sid),
            str(stored_call.get("employee_nama") or "-"),
        )

        return build_twiml(
            call_session_id=call_session_id,
            employee_phone=str(stored_call.get("employee_nomor_wa") or ""),
        )

    @staticmethod
    async def sync_status(call_session_id: str | None, request: Request) -> dict[str, Any]:
        call_session_id, payload = await ContactCallService._resolve_call_session_id(request, call_session_id)
        stored_call = AdminRepository.get_contact_call_by_session_id(call_session_id)
        if not stored_call:
            raise RuntimeError("Sesi telepon tidak ditemukan.")

        raw_status = str(payload.get("DialCallStatus") or payload.get("CallStatus") or "").strip()
        call_status = normalize_twilio_call_status(raw_status)
        twilio_call_sid = str(payload.get("DialCallSid") or payload.get("CallSid") or "").strip()
        call_detail = build_status_detail(
            employee_name=str(stored_call.get("employee_nama") or "karyawan"),
            status=call_status,
        )
        failure_reason = raw_status if call_status in {"busy", "no_response", "failed"} else ""

        updated = AdminRepository.update_contact_call_status(
            call_id=int(stored_call["id"]),
            call_status=call_status,
            call_detail=call_detail,
            call_provider=str(stored_call.get("call_provider") or call_provider()),
            provider_call_id=twilio_call_sid,
            twilio_call_sid=twilio_call_sid,
            provider_payload=payload,
            failure_reason=failure_reason,
            mark_connected=call_status == "connected",
            mark_ended=call_status not in ACTIVE_CALL_STATUSES,
        )
        _logger.info(
            "contact.call.status id=%s session=%s sid=%s status=%s raw=%s",
            ContactCallService._request_id(request),
            mask_value(call_session_id, head=6, tail=4),
            mask_value(twilio_call_sid),
            call_status,
            raw_status or "-",
        )
        return updated or stored_call
