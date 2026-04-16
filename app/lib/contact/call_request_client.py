import logging
from typing import Any

from config import settings
from lib.contact._http import post_json, request_timeout


_logger = logging.getLogger(__name__)


def _normalize_call_status(value: str | None) -> str:
    status = str(value or "").strip().lower()
    mapping = {
        "queued": "queued",
        "pending": "queued",
        "accepted": "queued",
        "ringing": "ringing",
        "calling": "ringing",
        "connected": "connected",
        "completed": "connected",
        "busy": "busy",
        "unavailable": "unavailable",
        "offline": "unavailable",
        "not_available": "unavailable",
        "no_response": "no_response",
        "no_answer": "no_response",
        "timeout": "no_response",
        "missed": "no_response",
        "failed": "failed",
        "error": "failed",
        "rejected": "failed",
    }
    return mapping.get(status, "queued")


def queue_contact_call(*, employee: dict[str, Any]) -> dict[str, Any]:
    mode = str(getattr(settings, "contact_call_mode", "dummy") or "dummy").strip().lower()
    if mode == "dummy":
        dummy_status = _normalize_call_status(getattr(settings, "contact_call_dummy_status", "no_response"))
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
            "provider_message_id": "",
            "provider_payload": {
                "mode": mode,
                "dummy_status": dummy_status,
                "employee_id": employee.get("id"),
                "employee_name": employee.get("nama"),
            },
        }

    if mode != "api":
        raise RuntimeError(f"CONTACT_CALL_MODE '{mode}' belum dikenali.")

    api_url = str(getattr(settings, "contact_call_api_url", "") or "").strip()
    api_key = str(getattr(settings, "contact_call_api_key", "") or "").strip()
    if not api_url:
        raise RuntimeError("CONTACT_CALL_API_URL wajib diisi untuk CONTACT_CALL_MODE=api.")

    payload: dict[str, Any] = {
        "channel": "call",
        "employee": {
            "employee_id": employee.get("id"),
            "employee_name": employee.get("nama"),
            "employee_department": employee.get("departemen"),
            "employee_position": employee.get("jabatan"),
            "employee_phone": employee.get("nomor_wa"),
        },
    }
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
        "provider_message_id": provider_message_id,
        "provider_payload": provider_payload,
    }
