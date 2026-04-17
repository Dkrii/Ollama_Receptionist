import requests
from typing import Any

from config import settings
from lib.contact.messaging.types import ContactMessageDispatchResult
from lib.contact.shared.http import post_form, request_timeout
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


def _resolve_test_target() -> tuple[str, bool]:
    # Temporary testing override: if WABLAS_TEST_GROUP_ID is filled, all messages
    # are routed to that WhatsApp group first. Leave it empty for normal personal sends.
    test_group_id = str(getattr(settings, "wablas_test_group_id", "") or "").strip()
    if test_group_id:
        return test_group_id, True
    return "", False


def _wablas_authorization_header() -> str:
    return (
        f"{str(getattr(settings, 'wablas_token', '') or '').strip()}."
        f"{str(getattr(settings, 'wablas_secret_key', '') or '').strip()}"
    )


def _extract_provider_message_id(provider_payload: dict[str, Any]) -> str:
    data = provider_payload.get("data")
    candidate_groups: list[Any] = []
    if isinstance(data, dict):
        candidate_groups.append(data.get("messages"))
        candidate_groups.append(data.get("message"))
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                candidate_groups.append(item.get("messages"))
                candidate_groups.append(item.get("message"))

    for group in candidate_groups:
        if isinstance(group, dict):
            message_id = str(group.get("id") or "").strip()
            if message_id:
                return message_id
            continue
        if isinstance(group, list):
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
        for key in ("messages", "message"):
            messages = data.get(key)
            if isinstance(messages, dict):
                candidate_statuses.append(str(messages.get("status") or "").strip().lower())
            elif isinstance(messages, list):
                for item in messages:
                    if isinstance(item, dict):
                        candidate_statuses.append(str(item.get("status") or "").strip().lower())
    elif isinstance(data, list):
        for entry in data:
            if not isinstance(entry, dict):
                continue
            for key in ("messages", "message"):
                messages = entry.get(key)
                if isinstance(messages, dict):
                    candidate_statuses.append(str(messages.get("status") or "").strip().lower())
                elif isinstance(messages, list):
                    for item in messages:
                        if isinstance(item, dict):
                            candidate_statuses.append(str(item.get("status") or "").strip().lower())

    for status in candidate_statuses:
        if status in {"sent", "delivered", "read"}:
            return "sent"
        if status in {"pending", "queue", "queued"}:
            return "queued"
    if provider_payload.get("status") is True:
        return "sent"
    return "queued"


def _provider_message(provider_payload: dict[str, Any]) -> str:
    return str(provider_payload.get("message") or "").strip()


def _build_failure_result(
    *,
    detail: str,
    request_url: str,
    request_payload: dict[str, Any],
    response_status_code: int | None,
    response_payload: dict[str, Any],
) -> ContactMessageDispatchResult:
    return {
        "provider": MESSAGING_PROVIDER_WABLAS,
        "status": "failed",
        "detail": detail,
        "provider_message_id": "",
        "provider_payload": {
            "request_url": request_url,
            "request_payload": request_payload,
            "response_status_code": response_status_code,
            "response_payload": response_payload,
        },
    }


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

    test_target, use_group_target = _resolve_test_target()
    if use_group_target:
        recipient = test_target

    payload_item: dict[str, Any] = {
        "phone": recipient,
        "message": message_text,
        "isGroup": "true" if use_group_target else "false",
    }

    request_payload_snapshot = dict(payload_item)
    request_url = f"{str(getattr(settings, 'wablas_base_url', '') or '').strip().rstrip('/')}/api/send-message"
    try:
        response, provider_payload = post_form(
            url=request_url,
            payload=payload_item,
            headers={"Authorization": _wablas_authorization_header()},
            timeout_seconds=request_timeout(getattr(settings, "wablas_timeout_seconds", 15), 15),
        )
    except requests.RequestException as exc:
        return _build_failure_result(
            detail="Koneksi ke provider Wablas gagal.",
            request_url=request_url,
            request_payload=request_payload_snapshot,
            response_status_code=None,
            response_payload={"error": str(exc)},
        )

    if not response.ok:
        provider_message = _provider_message(provider_payload)
        detail = (
            provider_message
            if provider_message
            else f"Provider Wablas merespons HTTP {response.status_code}."
        )
        return _build_failure_result(
            detail=detail,
            request_url=str(response.url or request_url),
            request_payload=request_payload_snapshot,
            response_status_code=response.status_code,
            response_payload=provider_payload,
        )

    if provider_payload.get("status") is False:
        provider_message = _provider_message(provider_payload)
        detail = provider_message if provider_message else "Provider Wablas menolak request pengiriman."
        return _build_failure_result(
            detail=detail,
            request_url=str(response.url or request_url),
            request_payload=request_payload_snapshot,
            response_status_code=response.status_code,
            response_payload=provider_payload,
        )

    dispatch_status = _extract_status(provider_payload)
    detail = (
        "Pesan WhatsApp berhasil diteruskan ke grup testing Wablas."
        if use_group_target and dispatch_status == "sent"
        else "Pesan WhatsApp berhasil diteruskan ke karyawan."
        if dispatch_status == "sent"
        else "Pesan WhatsApp diterima provider dan sedang diproses untuk grup testing Wablas."
        if use_group_target
        else "Pesan WhatsApp diterima provider dan sedang diproses."
    )
    return {
        "provider": MESSAGING_PROVIDER_WABLAS,
        "status": dispatch_status,
        "detail": detail,
        "provider_message_id": _extract_provider_message_id(provider_payload),
        "provider_payload": provider_payload,
    }
