import logging
import re
from typing import Any
from xml.sax.saxutils import escape

from config import settings
from lib.contact._http import post_form, post_json, request_timeout


_logger = logging.getLogger(__name__)


def _normalize_call_status(value: str | None) -> str:
    status = str(value or "").strip().lower()
    mapping = {
        "queued": "queued",
        "pending": "queued",
        "accepted": "queued",
        "ringing": "ringing",
        "calling": "ringing",
        "in-progress": "connected",
        "in_progress": "connected",
        "connected": "connected",
        "completed": "connected",
        "busy": "busy",
        "unavailable": "unavailable",
        "offline": "unavailable",
        "not_available": "unavailable",
        "no_response": "no_response",
        "no_answer": "no_response",
        "no-answer": "no_response",
        "timeout": "no_response",
        "missed": "no_response",
        "failed": "failed",
        "error": "failed",
        "rejected": "failed",
        "canceled": "failed",
        "cancelled": "failed",
    }
    return mapping.get(status, "queued")


def _build_twilio_twiml(*, employee: dict[str, Any]) -> str:
    employee_name = escape(str(employee.get("nama") or "rekan kerja"))
    return (
        "<Response>"
        f"<Say>Hello {employee_name}. There is a visitor waiting at the front desk. "
        "Please contact the receptionist as soon as possible.</Say>"
        "</Response>"
    )


def _extract_twilio_account_sid(api_url: str) -> str:
    match = re.search(r"/Accounts/([^/]+)/Calls(?:\.json)?$", str(api_url or "").strip(), re.IGNORECASE)
    return str(match.group(1) if match else "").strip()


def queue_contact_call(*, employee: dict[str, Any]) -> dict[str, Any]:
    app_env = str(getattr(settings, "app_env", "development") or "development").strip().lower()
    if app_env != "production":
        dummy_status = "no_response"
        if dummy_status == "connected":
            detail = (
                f"Saya sudah mencoba menghubungi {employee.get('nama', 'karyawan')} "
                "dan panggilan berhasil tersambung."
            )
        elif dummy_status in {"busy", "unavailable", "no_response"}:
            detail = (
                f"Saya sudah mencoba menghubungi {employee.get('nama', 'karyawan')}, "
                "tetapi belum ada respons."
            )
        else:
            detail = f"Permintaan panggilan untuk {employee.get('nama', 'karyawan')} diterima di mode dummy."
        return {
            "provider": "dummy",
            "status": dummy_status,
            "detail": detail,
            "provider_call_id": "",
            "provider_message_id": "",
            "provider_payload": {
                "app_env": app_env,
                "dummy_status": dummy_status,
                "employee_id": employee.get("id"),
                "employee_name": employee.get("nama"),
            },
        }

    api_url = str(getattr(settings, "contact_call_api_url", "") or "").strip()
    api_key = str(getattr(settings, "contact_call_api_key", "") or "").strip()
    from_number = str(getattr(settings, "contact_call_from_number", "") or "").strip()
    to_number = str(employee.get("nomor_wa") or "").strip()
    if not api_url or not api_key:
        raise RuntimeError("CONTACT_CALL_API_URL dan CONTACT_CALL_API_KEY wajib diisi untuk APP_ENV=production.")
    if not to_number:
        raise RuntimeError("Nomor telepon karyawan belum tersedia.")

    if "twilio.com" in api_url.lower():
        account_sid = _extract_twilio_account_sid(api_url)
        if not account_sid:
            raise RuntimeError("CONTACT_CALL_API_URL Twilio harus memakai format /Accounts/{AccountSid}/Calls.json")
        if not from_number:
            raise RuntimeError("CONTACT_CALL_FROM_NUMBER wajib diisi untuk panggilan production.")

        payload: dict[str, Any] = {
            "To": to_number,
            "From": from_number,
            "Twiml": _build_twilio_twiml(employee=employee),
        }
        _, provider_payload = post_form(
            url=api_url,
            payload=payload,
            basic_auth_username=account_sid,
            basic_auth_password=api_key,
            timeout_seconds=request_timeout("contact_call_timeout_seconds", 15),
        )
        provider_call_id = str(
            provider_payload.get("sid")
            or provider_payload.get("call_sid")
            or provider_payload.get("id")
            or ""
        ).strip()
        normalized_status = _normalize_call_status(provider_payload.get("status"))
        detail = str(
            provider_payload.get("message")
            or provider_payload.get("detail")
            or f"Permintaan panggilan untuk {employee.get('nama', 'karyawan')} sudah diteruskan lewat Twilio."
        ).strip()

        _logger.info(
            "contact.call provider=twilio employee=%s status=%s call_sid=%s",
            employee.get("nama"),
            normalized_status,
            provider_call_id or "-",
        )

        return {
            "provider": "twilio",
            "status": normalized_status,
            "detail": detail,
            "provider_call_id": provider_call_id,
            "provider_message_id": provider_call_id,
            "provider_payload": provider_payload,
        }

    payload: dict[str, Any] = {
        "channel": "call",
        "employee": {
            "employee_id": employee.get("id"),
            "employee_name": employee.get("nama"),
            "employee_department": employee.get("departemen"),
            "employee_position": employee.get("jabatan"),
            "employee_phone": to_number,
        },
    }
    if from_number:
        payload["from_number"] = from_number
    _, provider_payload = post_json(
        url=api_url,
        payload=payload,
        bearer_token=api_key,
        timeout_seconds=request_timeout("contact_call_timeout_seconds", 15),
    )
    provider_message_id = str(
        provider_payload.get("request_id")
        or provider_payload.get("call_id")
        or provider_payload.get("id")
        or ""
    ).strip()
    normalized_status = _normalize_call_status(
        provider_payload.get("status") or provider_payload.get("call_status")
    )
    detail = str(
        provider_payload.get("detail")
        or provider_payload.get("message")
        or f"Permintaan panggilan untuk {employee.get('nama', 'karyawan')} sudah diteruskan."
    ).strip()

    _logger.info(
        "contact.call provider=api employee=%s status=%s request_id=%s",
        employee.get("nama"),
        normalized_status,
        provider_message_id or "-",
    )

    return {
        "provider": "contact_call_api",
        "status": normalized_status,
        "detail": detail,
        "provider_call_id": provider_message_id,
        "provider_message_id": provider_message_id,
        "provider_payload": provider_payload,
    }
