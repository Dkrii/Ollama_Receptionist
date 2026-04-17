from typing import Any

from config import settings
from lib.contact.call.types import ContactCallResult, ContactCallStatusUpdate
from lib.contact.call.utils import (
    ACTIVE_CALL_STATUSES,
    build_call_status_detail,
    build_dev_identity,
    create_call_session_id,
    public_url,
)
from lib.contact.shared.phone import require_contact_phone


CALL_PROVIDER_TWILIO = "twilio"


def require_twilio_settings() -> None:
    missing: list[str] = []
    if not str(getattr(settings, "twilio_account_sid", "") or "").strip():
        missing.append("TWILIO_ACCOUNT_SID")
    if not str(getattr(settings, "twilio_api_key_sid", "") or "").strip():
        missing.append("TWILIO_API_KEY_SID")
    if not str(getattr(settings, "twilio_api_key_secret", "") or "").strip():
        missing.append("TWILIO_API_KEY_SECRET")
    if not str(getattr(settings, "twilio_twiml_app_sid", "") or "").strip():
        missing.append("TWILIO_TWIML_APP_SID")
    if not str(getattr(settings, "contact_call_from_number", "") or "").strip():
        missing.append("CONTACT_CALL_FROM_NUMBER")
    if not str(getattr(settings, "app_url", "") or "").strip():
        missing.append("APP_URL")
    if missing:
        raise RuntimeError("Konfigurasi Twilio belum lengkap: " + ", ".join(missing))


def validate_twilio_setting_shapes() -> None:
    validations = (
        ("TWILIO_ACCOUNT_SID", str(getattr(settings, "twilio_account_sid", "") or "").strip(), "AC"),
        ("TWILIO_API_KEY_SID", str(getattr(settings, "twilio_api_key_sid", "") or "").strip(), "SK"),
        ("TWILIO_TWIML_APP_SID", str(getattr(settings, "twilio_twiml_app_sid", "") or "").strip(), "AP"),
    )
    for setting_name, value, prefix in validations:
        if value and not value.startswith(prefix):
            raise RuntimeError(f"{setting_name} harus diawali {prefix}.")


def create_access_token(*, identity: str) -> str:
    from twilio.jwt.access_token import AccessToken
    from twilio.jwt.access_token.grants import VoiceGrant

    require_twilio_settings()
    validate_twilio_setting_shapes()

    token = AccessToken(
        str(settings.twilio_account_sid),
        str(settings.twilio_api_key_sid),
        str(settings.twilio_api_key_secret),
        identity=str(identity),
        ttl=3600,
    )
    token.add_grant(
        VoiceGrant(
            outgoing_application_sid=str(settings.twilio_twiml_app_sid),
            incoming_allow=False,
        )
    )
    raw_token = token.to_jwt()
    return raw_token.decode("utf-8") if isinstance(raw_token, bytes) else str(raw_token)


def normalize_twilio_call_status(value: str | None) -> str:
    status = str(value or "").strip().lower()
    mapping = {
        "queued": "preparing",
        "initiated": "dialing_employee",
        "calling": "dialing_employee",
        "ringing": "ringing",
        "answered": "connected",
        "in-progress": "connected",
        "in_progress": "connected",
        "completed": "completed",
        "busy": "busy",
        "failed": "failed",
        "canceled": "failed",
        "cancelled": "failed",
        "no-answer": "no_response",
        "no_answer": "no_response",
    }
    return mapping.get(status, "preparing")


def build_status_detail(*, employee_name: str, status: str) -> str:
    return build_call_status_detail(status)


def issue_access_token(*, identity: str, call_session_id: str) -> dict[str, Any]:
    return {
        "token": create_access_token(identity=identity),
        "identity": identity,
        "call_session_id": call_session_id,
    }


def create_call_session(employee: dict[str, Any]) -> ContactCallResult:
    employee_name = str(employee.get("nama") or "karyawan")
    call_session_id = create_call_session_id()
    dev_identity = build_dev_identity(call_session_id)

    failure_reason = ""
    initial_status = "preparing"
    initial_detail = build_status_detail(employee_name=employee_name, status="preparing")
    provider_payload: dict[str, Any] = {"channel": "two_way_call"}

    try:
        require_contact_phone(employee)
        require_twilio_settings()
    except Exception as exc:
        failure_reason = str(exc)
        initial_status = "failed"
        initial_detail = build_status_detail(employee_name=employee_name, status="failed")
        provider_payload["setup_error"] = failure_reason

    return {
        "provider": CALL_PROVIDER_TWILIO,
        "status": initial_status,
        "detail": initial_detail,
        "session_id": call_session_id,
        "provider_call_id": "",
        "provider_payload": provider_payload,
        "dev_identity": dev_identity,
        "failure_reason": failure_reason,
    }


def build_twiml(*, call_session_id: str, employee_phone: str) -> str:
    from twilio.twiml.voice_response import Dial, Number, VoiceResponse

    callback_url = public_url("/api/contact/call/status")
    response = VoiceResponse()
    dial = Dial(
        answer_on_bridge=True,
        caller_id=str(settings.contact_call_from_number),
        action=f"{callback_url}?call_session_id={call_session_id}&source=dial_action",
        method="POST",
    )
    dial.append(
        Number(
            employee_phone,
            status_callback=f"{callback_url}?call_session_id={call_session_id}&source=employee_leg",
            status_callback_event="initiated ringing answered completed",
            status_callback_method="POST",
        )
    )
    response.append(dial)
    return str(response)


def render_twiml(*, call_session_id: str, employee_phone: str) -> str:
    return build_twiml(call_session_id=call_session_id, employee_phone=employee_phone)


def parse_status_payload(*, payload: dict[str, Any], employee_name: str) -> ContactCallStatusUpdate:
    raw_status = str(payload.get("DialCallStatus") or payload.get("CallStatus") or "").strip()
    status = normalize_twilio_call_status(raw_status)
    provider_call_id = str(payload.get("DialCallSid") or payload.get("CallSid") or "").strip()
    failure_reason = raw_status if status in {"busy", "no_response", "failed"} else ""
    return {
        "status": status,
        "detail": build_status_detail(employee_name=employee_name, status=status),
        "provider_call_id": provider_call_id,
        "provider_payload": payload,
        "failure_reason": failure_reason,
        "mark_connected": status == "connected",
        "mark_ended": status not in ACTIVE_CALL_STATUSES,
    }


def parse_client_status_payload(*, payload: dict[str, Any], employee_name: str) -> ContactCallStatusUpdate:
    raw_status = str(payload.get("status") or "").strip()
    status = normalize_twilio_call_status(raw_status)
    provider_call_id = str(payload.get("provider_call_id") or payload.get("CallSid") or "").strip()
    failure_reason = raw_status if status in {"busy", "no_response", "failed"} else ""
    return {
        "status": status,
        "detail": build_status_detail(employee_name=employee_name, status=status),
        "provider_call_id": provider_call_id,
        "provider_payload": payload,
        "failure_reason": failure_reason,
        "mark_connected": status == "connected",
        "mark_ended": status not in ACTIVE_CALL_STATUSES,
    }
