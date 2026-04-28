import uuid
from typing import Any

from modules.contacts.call.types import ContactCallResult, ContactCallStatusUpdate
from modules.contacts.call.utils import ACTIVE_CALL_STATUSES
from modules.contacts.registry import (
    get_contact_call_provider,
    get_contact_call_provider_adapter,
)

UNSUPPORTED_PROVIDER_ERROR = "unsupported_call_provider"


def create_contact_call_session(employee: dict[str, Any]) -> ContactCallResult:
    provider = get_contact_call_provider()
    adapter = get_contact_call_provider_adapter(provider)
    if adapter is not None:
        return adapter.create_call_session(employee)

    session_id = uuid.uuid4().hex
    return {
        "provider": provider,
        "status": "failed",
        "detail": f"Provider call '{provider}' belum didukung.",
        "session_id": session_id,
        "provider_call_id": "",
        "provider_payload": {"error": UNSUPPORTED_PROVIDER_ERROR},
        "dev_identity": f"dev-call-{session_id}",
        "failure_reason": UNSUPPORTED_PROVIDER_ERROR,
    }


def issue_contact_call_access_token(
    *,
    provider: str,
    identity: str,
    call_session_id: str,
) -> dict[str, Any]:
    normalized_provider = str(provider or get_contact_call_provider()).strip().lower()
    adapter = get_contact_call_provider_adapter(normalized_provider)
    if adapter is None:
        raise RuntimeError(f"Provider call '{normalized_provider}' belum didukung.")

    token_payload = adapter.issue_access_token(identity=identity, call_session_id=call_session_id)
    if not isinstance(token_payload, dict):
        raise RuntimeError(f"Provider call '{normalized_provider}' mengembalikan payload token tidak valid.")

    resolved_payload = dict(token_payload)
    resolved_payload.setdefault("provider", normalized_provider)
    resolved_payload.setdefault("identity", identity)
    resolved_payload.setdefault("call_session_id", call_session_id)
    return resolved_payload


def render_contact_call_twiml(
    *,
    provider: str,
    call_session_id: str,
    employee_phone: str,
) -> str:
    normalized_provider = str(provider or get_contact_call_provider()).strip().lower()
    adapter = get_contact_call_provider_adapter(normalized_provider)
    if adapter is None:
        raise RuntimeError(f"Provider call '{normalized_provider}' belum didukung.")
    return adapter.render_twiml(call_session_id=call_session_id, employee_phone=employee_phone)


def parse_contact_call_status_payload(
    *,
    provider: str,
    payload: dict[str, Any],
    employee_name: str,
) -> ContactCallStatusUpdate:
    normalized_provider = str(provider or get_contact_call_provider()).strip().lower()
    adapter = get_contact_call_provider_adapter(normalized_provider)
    if adapter is not None:
        return adapter.parse_status_payload(payload=payload, employee_name=employee_name)
    return {
        "status": "failed",
        "detail": f"Provider call '{normalized_provider}' belum didukung.",
        "provider_call_id": "",
        "provider_payload": payload,
        "failure_reason": UNSUPPORTED_PROVIDER_ERROR,
        "mark_connected": False,
        "mark_ended": True,
    }


def parse_contact_call_client_status_payload(
    *,
    provider: str,
    payload: dict[str, Any],
    employee_name: str,
) -> ContactCallStatusUpdate:
    normalized_provider = str(provider or get_contact_call_provider()).strip().lower()
    adapter = get_contact_call_provider_adapter(normalized_provider)
    if adapter is not None:
        return adapter.parse_client_status_payload(payload=payload, employee_name=employee_name)
    return {
        "status": "failed",
        "detail": f"Provider call '{normalized_provider}' belum didukung.",
        "provider_call_id": "",
        "provider_payload": payload,
        "failure_reason": UNSUPPORTED_PROVIDER_ERROR,
        "mark_connected": False,
        "mark_ended": True,
    }


def build_contact_call_status_detail(*, provider: str, employee_name: str, status: str) -> str:
    normalized_provider = str(provider or get_contact_call_provider()).strip().lower()
    adapter = get_contact_call_provider_adapter(normalized_provider)
    if adapter is not None:
        return adapter.build_status_detail(employee_name=employee_name, status=status)
    return "Tidak terhubung."


def mask_contact_value(value: str | None, *, head: int = 4, tail: int = 4) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    if len(text) <= (head + tail):
        return text
    return f"{text[:head]}...{text[-tail:]}"
