from typing import Any

from lib.contact.call.providers import twilio
from lib.contact.call.types import ContactCallResult, ContactCallStatusUpdate
from lib.contact.shared.registry import get_contact_call_provider


ACTIVE_CALL_STATUSES = set(twilio.ACTIVE_CALL_STATUSES)


def create_contact_call_session(employee: dict[str, Any]) -> ContactCallResult:
    provider = get_contact_call_provider()
    if provider == twilio.CALL_PROVIDER_TWILIO:
        return twilio.create_call_session(employee)

    session_id = twilio.create_call_session_id()
    return {
        "provider": provider,
        "status": "failed",
        "detail": f"Provider call '{provider}' belum didukung.",
        "session_id": session_id,
        "provider_call_id": "",
        "provider_payload": {"error": "unsupported_call_provider"},
        "dev_identity": twilio.build_dev_identity(session_id),
        "failure_reason": "unsupported_call_provider",
    }


def issue_contact_call_access_token(
    *,
    provider: str,
    identity: str,
    call_session_id: str,
) -> dict[str, Any]:
    normalized_provider = str(provider or get_contact_call_provider()).strip().lower()
    if normalized_provider == twilio.CALL_PROVIDER_TWILIO:
        return {
            "provider": normalized_provider,
            "token": twilio.create_access_token(identity=identity),
            "identity": identity,
            "call_session_id": call_session_id,
        }
    raise RuntimeError(f"Provider call '{normalized_provider}' tidak mendukung access token.")


def render_contact_call_twiml(
    *,
    provider: str,
    call_session_id: str,
    employee_phone: str,
) -> str:
    normalized_provider = str(provider or get_contact_call_provider()).strip().lower()
    if normalized_provider == twilio.CALL_PROVIDER_TWILIO:
        return twilio.build_twiml(call_session_id=call_session_id, employee_phone=employee_phone)
    raise RuntimeError(f"Provider call '{normalized_provider}' tidak mendukung TwiML.")


def parse_contact_call_status_payload(
    *,
    provider: str,
    payload: dict[str, Any],
    employee_name: str,
) -> ContactCallStatusUpdate:
    normalized_provider = str(provider or get_contact_call_provider()).strip().lower()
    if normalized_provider == twilio.CALL_PROVIDER_TWILIO:
        return twilio.parse_status_payload(payload=payload, employee_name=employee_name)
    return {
        "status": "failed",
        "detail": f"Provider call '{normalized_provider}' belum didukung.",
        "provider_call_id": "",
        "provider_payload": payload,
        "failure_reason": "unsupported_call_provider",
        "mark_connected": False,
        "mark_ended": True,
    }


def build_contact_call_status_detail(*, provider: str, employee_name: str, status: str) -> str:
    normalized_provider = str(provider or get_contact_call_provider()).strip().lower()
    if normalized_provider == twilio.CALL_PROVIDER_TWILIO:
        return twilio.build_status_detail(employee_name=employee_name, status=status)
    return "Tidak terhubung."


def mask_contact_value(value: str | None, *, head: int = 4, tail: int = 4) -> str:
    return twilio.mask_value(value, head=head, tail=tail)
