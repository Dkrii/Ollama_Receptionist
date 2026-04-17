from typing import Any

from config import settings
from lib.contact.messaging.types import ContactMessageDispatchResult
from lib.contact.shared.http import post_json, request_timeout
from lib.contact.shared.phone import normalize_indonesia_phone, require_contact_phone


MESSAGING_PROVIDER_WABLAS = "wablas"


def missing_wablas_settings() -> list[str]:
    missing: list[str] = []
    if not str(getattr(settings, "wablas_base_url", "") or "").strip():
        missing.append("WABLAS_BASE_URL")
    if not str(getattr(settings, "wablas_token", "") or "").strip():
        missing.append("WABLAS_TOKEN")
    if not str(getattr(settings, "wablas_secret_key", "") or "").strip():
        missing.append("WABLAS_SECRET_KEY")
    return missing


def is_configured() -> bool:
    return not missing_wablas_settings()


def _extract_provider_message_id(provider_payload: dict[str, Any]) -> str:
    data = provider_payload.get("data")
    candidate_groups: list[Any] = []
    if isinstance(data, dict):
        candidate_groups.append(data.get("messages"))
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                candidate_groups.append(item.get("messages"))

    for group in candidate_groups:
        if not isinstance(group, list):
            continue
        for message in group:
            if not isinstance(message, dict):
                continue
            message_id = str(message.get("id") or "").strip()
            if message_id:
                return message_id
    return ""


def _extract_status(provider_payload: dict[str, Any]) -> str:
    data = provider_payload.get("data")
    candidate_statuses: list[str] = []
    if isinstance(data, dict):
        messages = data.get("messages")
        if isinstance(messages, list):
            for item in messages:
                if isinstance(item, dict):
                    candidate_statuses.append(str(item.get("status") or "").strip().lower())
    elif isinstance(data, list):
        for entry in data:
            if not isinstance(entry, dict):
                continue
            messages = entry.get("messages")
            if not isinstance(messages, list):
                continue
            for item in messages:
                if isinstance(item, dict):
                    candidate_statuses.append(str(item.get("status") or "").strip().lower())

    for status in candidate_statuses:
        if status in {"sent", "delivered", "read"}:
            return "sent"
        if status in {"pending", "queue", "queued"}:
            return "queued"
    return "queued"


def dispatch_message(
    *,
    employee: dict[str, Any],
    visitor_name: str,
    visitor_goal: str,
    message_text: str,
    message_id: int | None = None,
) -> ContactMessageDispatchResult:
    missing_settings = missing_wablas_settings()
    if missing_settings:
        return {
            "provider": "dummy",
            "status": "sent_dummy",
            "detail": "Dummy messaging dispatcher aktif karena konfigurasi provider belum lengkap.",
            "provider_message_id": "",
            "provider_payload": {
                "configured": False,
                "missing_settings": missing_settings,
                "employee_id": employee.get("id"),
                "employee_name": employee.get("nama"),
            },
        }

    raw_phone = require_contact_phone(employee)
    recipient = normalize_indonesia_phone(raw_phone)
    if not recipient:
        raise RuntimeError("Nomor WhatsApp karyawan tidak valid untuk provider messaging.")

    payload_item: dict[str, Any] = {
        "phone": recipient,
        "message": message_text,
        "isGroup": "false",
    }
    if message_id is not None:
        payload_item["ref_id"] = str(message_id)

    _, provider_payload = post_json(
        url=f"{str(getattr(settings, 'wablas_base_url', '') or '').strip().rstrip('/')}/api/v2/send-message",
        payload={"data": [payload_item]},
        headers={
            "Authorization": (
                f"{str(getattr(settings, 'wablas_token', '') or '').strip()}."
                f"{str(getattr(settings, 'wablas_secret_key', '') or '').strip()}"
            ),
        },
        timeout_seconds=request_timeout(getattr(settings, "wablas_timeout_seconds", 15), 15),
    )

    dispatch_status = _extract_status(provider_payload)
    detail = (
        "Pesan WhatsApp berhasil diteruskan ke karyawan."
        if dispatch_status == "sent"
        else "Pesan WhatsApp diterima provider dan sedang diproses."
    )
    return {
        "provider": MESSAGING_PROVIDER_WABLAS,
        "status": dispatch_status,
        "detail": detail,
        "provider_message_id": _extract_provider_message_id(provider_payload),
        "provider_payload": provider_payload,
    }
