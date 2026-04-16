import logging
from typing import Any

from config import settings
from lib.contact._http import post_json, request_timeout


_logger = logging.getLogger(__name__)


def dispatch_contact_message(
    *,
    employee: dict[str, Any],
    visitor_name: str,
    visitor_goal: str,
    message_text: str,
) -> dict[str, Any]:
    app_env = str(getattr(settings, "app_env", "development") or "development").strip().lower()

    if app_env != "production":
        return {
            "provider": "dummy",
            "status": "sent_dummy",
            "detail": "Dummy WhatsApp dispatcher berhasil (simulasi tanpa API key).",
            "provider_message_id": "",
            "provider_payload": {
                "app_env": app_env,
                "employee_id": employee.get("id"),
                "employee_name": employee.get("nama"),
            },
        }

    base_url = str(getattr(settings, "whatsapp_api_base_url", "") or "").strip()
    api_key = str(getattr(settings, "whatsapp_api_key", "") or "").strip()
    if not base_url or not api_key:
        raise RuntimeError("WHATSAPP_API_BASE_URL dan WHATSAPP_API_KEY wajib diisi untuk mode production.")
    recipient = str(employee.get("nomor_wa") or "").strip()
    if not recipient:
        raise RuntimeError("Nomor WhatsApp karyawan belum tersedia.")

    payload: dict[str, Any] = {
        "channel": "whatsapp",
        "sender_id": str(getattr(settings, "whatsapp_sender_id", "") or "").strip(),
        "to": recipient,
        "message": message_text,
        "context": {
            "employee_id": employee.get("id"),
            "employee_name": employee.get("nama"),
            "employee_department": employee.get("departemen"),
            "visitor_name": visitor_name,
            "visitor_goal": visitor_goal,
        },
    }
    if not payload["sender_id"]:
        payload.pop("sender_id", None)

    _, provider_payload = post_json(
        url=base_url,
        payload=payload,
        bearer_token=api_key,
        timeout_seconds=request_timeout("whatsapp_timeout_seconds", 15),
    )
    provider_message_id = str(
        provider_payload.get("message_id")
        or provider_payload.get("id")
        or ((provider_payload.get("messages") or [{}])[0].get("id") if isinstance(provider_payload.get("messages"), list) else "")
        or ""
    ).strip()

    _logger.info(
        "contact.dispatch provider=whatsapp_api employee=%s message_id=%s",
        employee.get("nama"),
        provider_message_id or "-",
    )

    return {
        "provider": "whatsapp_api",
        "status": "sent",
        "detail": "Pesan WhatsApp berhasil diteruskan ke karyawan.",
        "provider_message_id": provider_message_id,
        "provider_payload": provider_payload,
    }
