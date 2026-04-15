import logging
from typing import Any

import requests

from config import settings


_logger = logging.getLogger(__name__)
_http_session = requests.Session()


def normalize_contact_mode(value: str | None) -> str:
    mode = str(value or "").strip().lower()
    if mode in {"call", "notify"}:
        return mode

    default_mode = str(getattr(settings, "contact_default_mode", "notify") or "notify").strip().lower()
    return default_mode if default_mode in {"call", "notify"} else "notify"


def _response_payload(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
        return payload if isinstance(payload, dict) else {"payload": payload}
    except Exception:
        text = (response.text or "").strip()
        return {"raw_text": text[:1000]}


def queue_contact_call(*, employee: dict[str, Any]) -> dict[str, Any]:
    mode = str(getattr(settings, "contact_call_mode", "dummy") or "dummy").strip().lower()
    if mode != "dummy":
        raise RuntimeError("CONTACT_CALL_MODE production belum dikonfigurasi.")

    return {
        "provider": "dummy",
        "status": "queued_dummy",
        "detail": f"Permintaan panggilan untuk {employee.get('nama', 'karyawan')} diterima di mode dummy.",
        "provider_message_id": "",
        "provider_payload": {
            "mode": mode,
            "employee_id": employee.get("id"),
            "employee_name": employee.get("nama"),
        },
    }


def dispatch_contact_message(
    *,
    employee: dict[str, Any],
    visitor_name: str,
    visitor_goal: str,
    message_text: str,
) -> dict[str, Any]:
    mode = str(getattr(settings, "contact_message_delivery_mode", "dummy") or "dummy").strip().lower()

    if mode != "whatsapp_api":
        return {
            "provider": "dummy",
            "status": "sent_dummy",
            "detail": "Dummy WhatsApp dispatcher berhasil (simulasi tanpa API key).",
            "provider_message_id": "",
            "provider_payload": {
                "mode": mode,
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

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    response = _http_session.post(
        base_url,
        json=payload,
        headers=headers,
        timeout=max(5, int(getattr(settings, "whatsapp_timeout_seconds", 15) or 15)),
    )
    response.raise_for_status()
    provider_payload = _response_payload(response)
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
