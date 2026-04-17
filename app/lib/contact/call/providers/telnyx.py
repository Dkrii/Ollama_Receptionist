from typing import Any

import requests

from config import settings
from lib.contact.call.types import ContactCallResult, ContactCallStatusUpdate
from lib.contact.call.utils import (
    ACTIVE_CALL_STATUSES,
    build_call_status_detail,
    build_dev_identity,
    create_call_session_id,
)
from lib.contact.shared.http import request_timeout
from lib.contact.shared.phone import normalize_indonesia_e164_phone, require_contact_phone


CALL_PROVIDER_TELNYX = "telnyx"


def missing_telnyx_settings() -> list[str]:
    missing: list[str] = []
    if not str(getattr(settings, "telnyx_api_base_url", "") or "").strip():
        missing.append("TELNYX_API_BASE_URL")
    if not str(getattr(settings, "telnyx_api_key", "") or "").strip():
        missing.append("TELNYX_API_KEY")
    if not str(getattr(settings, "telnyx_telephony_credential_id", "") or "").strip():
        missing.append("TELNYX_TELEPHONY_CREDENTIAL_ID")
    if not str(getattr(settings, "telnyx_caller_id_number", "") or "").strip():
        missing.append("TELNYX_CALLER_ID_NUMBER")
    return missing


def is_configured() -> bool:
    return not missing_telnyx_settings()


def _extract_provider_call_id(payload: dict[str, Any]) -> str:
    candidates = (
        payload.get("provider_call_id"),
        payload.get("call_id"),
        payload.get("callId"),
        payload.get("id"),
    )
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text

    call = payload.get("call")
    if isinstance(call, dict):
        for key in ("id", "call_id", "callId", "telnyxCallControlId"):
            text = str(call.get(key) or "").strip()
            if text:
                return text
    return ""


def _normalize_telnyx_status(raw_status: str | None) -> str:
    normalized = str(raw_status or "").strip().lower()
    mapping = {
        "preparing": "preparing",
        "new": "preparing",
        "requesting": "dialing_employee",
        "trying": "dialing_employee",
        "recovering": "dialing_employee",
        "dialing_employee": "dialing_employee",
        "ringing": "ringing",
        "answering": "ringing",
        "early": "ringing",
        "active": "connected",
        "held": "connected",
        "connected": "connected",
        "busy": "busy",
        "hangup": "completed",
        "destroy": "completed",
        "purge": "completed",
        "completed": "completed",
        "failed": "failed",
        "error": "failed",
        "no_response": "no_response",
        "timeout": "no_response",
        "rejected": "busy",
    }
    return mapping.get(normalized, "failed")


def _build_status_update(*, raw_status: str | None, payload: dict[str, Any], employee_name: str) -> ContactCallStatusUpdate:
    status = _normalize_telnyx_status(raw_status)
    return {
        "status": status,
        "detail": build_status_detail(employee_name=employee_name, status=status),
        "provider_call_id": _extract_provider_call_id(payload),
        "provider_payload": payload,
        "failure_reason": str(raw_status or "").strip().lower() if status in {"busy", "failed", "no_response"} else "",
        "mark_connected": status == "connected",
        "mark_ended": status not in ACTIVE_CALL_STATUSES,
    }


def issue_access_token(*, identity: str, call_session_id: str) -> dict[str, Any]:
    missing = missing_telnyx_settings()
    if missing:
        raise RuntimeError("Konfigurasi Telnyx belum lengkap: " + ", ".join(missing))

    response = requests.post(
        (
            f"{str(getattr(settings, 'telnyx_api_base_url', '') or '').strip().rstrip('/')}"
            f"/v2/telephony_credentials/{str(getattr(settings, 'telnyx_telephony_credential_id', '') or '').strip()}/token"
        ),
        headers={
            "Authorization": f"Bearer {str(getattr(settings, 'telnyx_api_key', '') or '').strip()}",
            "Content-Type": "application/json",
        },
        timeout=request_timeout(getattr(settings, "telnyx_timeout_seconds", 15), 15),
    )
    response.raise_for_status()

    token = ""
    try:
        payload = response.json()
        if isinstance(payload, str):
            token = payload.strip()
        elif isinstance(payload, dict):
            token = str(payload.get("data") or payload.get("token") or "").strip()
    except Exception:
        token = str(response.text or "").strip()

    token = token.strip('"').strip()
    if not token:
        raise RuntimeError("Token Telnyx tidak ditemukan di response provider.")

    return {
        "token": token,
        "identity": identity,
        "caller_number": str(getattr(settings, "telnyx_caller_id_number", "") or "").strip(),
        "call_session_id": call_session_id,
    }


def build_status_detail(*, employee_name: str, status: str) -> str:
    return build_call_status_detail(status)


def create_call_session(employee: dict[str, Any]) -> ContactCallResult:
    employee_name = str(employee.get("nama") or "karyawan")
    call_session_id = create_call_session_id()
    dev_identity = build_dev_identity(call_session_id)

    failure_reason = ""
    initial_status = "preparing"
    initial_detail = build_status_detail(employee_name=employee_name, status="preparing")
    provider_payload: dict[str, Any] = {
        "channel": "two_way_call",
        "transport": "webrtc",
    }

    try:
        require_contact_phone(employee)
        normalized_phone = normalize_indonesia_e164_phone(str(employee.get("nomor_wa") or ""))
        if not normalized_phone:
            raise RuntimeError("Nomor telepon karyawan tidak valid untuk Telnyx.")
        missing_settings = missing_telnyx_settings()
        if missing_settings:
            raise RuntimeError("Konfigurasi Telnyx belum lengkap: " + ", ".join(missing_settings))
        provider_payload["destination_number"] = normalized_phone
    except Exception as exc:
        failure_reason = str(exc)
        initial_status = "failed"
        initial_detail = build_status_detail(employee_name=employee_name, status="failed")
        provider_payload["setup_error"] = failure_reason

    return {
        "provider": CALL_PROVIDER_TELNYX,
        "status": initial_status,
        "detail": initial_detail,
        "session_id": call_session_id,
        "provider_call_id": "",
        "provider_payload": provider_payload,
        "dev_identity": dev_identity,
        "failure_reason": failure_reason,
    }


def render_twiml(*, call_session_id: str, employee_phone: str) -> str:
    raise RuntimeError("Provider call 'telnyx' tidak mendukung TwiML.")


def parse_status_payload(*, payload: dict[str, Any], employee_name: str) -> ContactCallStatusUpdate:
    raw_status = str(
        payload.get("status")
        or payload.get("state")
        or payload.get("call_state")
        or ""
    ).strip()
    return _build_status_update(raw_status=raw_status, payload=payload, employee_name=employee_name)


def parse_client_status_payload(*, payload: dict[str, Any], employee_name: str) -> ContactCallStatusUpdate:
    raw_status = str(payload.get("status") or "").strip()
    return _build_status_update(raw_status=raw_status, payload=payload, employee_name=employee_name)
