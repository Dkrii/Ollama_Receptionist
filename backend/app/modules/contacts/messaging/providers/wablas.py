import random
import time
import requests
from typing import Any

from config import settings
from modules.contacts.messaging.types import ContactMessageDispatchResult
from modules.contacts.http import post_form, request_timeout
from modules.contacts.phone import normalize_indonesia_phone, require_contact_phone


MESSAGING_PROVIDER_WABLAS = "wablas"
_RETRYABLE_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}


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


def _collect_message_statuses(provider_payload: dict[str, Any]) -> list[str]:
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
    return candidate_statuses


def _provider_acknowledged(provider_payload: dict[str, Any]) -> bool:
    return provider_payload.get("status") is True and bool(_extract_provider_message_id(provider_payload))


def _extract_status(provider_payload: dict[str, Any]) -> str:
    candidate_statuses = _collect_message_statuses(provider_payload)

    for status in candidate_statuses:
        if status in {"failed", "error", "cancelled", "rejected"}:
            return "failed"
    for status in candidate_statuses:
        if status in {"sent", "delivered", "read"}:
            return "sent"
    for status in candidate_statuses:
        if status in {"pending", "queue", "queued"}:
            if _provider_acknowledged(provider_payload):
                return "accepted"
            return "queued"
    if _provider_acknowledged(provider_payload):
        return "accepted"
    if provider_payload.get("status") is True:
        return "sent"
    return "queued"


def _provider_message(provider_payload: dict[str, Any]) -> str:
    return str(provider_payload.get("message") or "").strip()


def _retry_attempts() -> int:
    try:
        value = int(getattr(settings, "wablas_retry_attempts", 3) or 3)
    except Exception:
        value = 3
    return max(1, min(value, 5))


def _retry_backoff_seconds() -> float:
    try:
        value = float(getattr(settings, "wablas_retry_backoff_seconds", 0.4) or 0.4)
    except Exception:
        value = 0.4
    return max(0.0, min(value, 3.0))


def _build_retry_delay(attempt_number: int) -> float:
    base_delay = _retry_backoff_seconds()
    if base_delay <= 0:
        return 0.0
    exponential_delay = base_delay * (2 ** max(0, attempt_number - 1))
    jitter = random.uniform(0.0, base_delay * 0.25)
    return exponential_delay + jitter


def _build_attempt_entry(
    *,
    attempt: int,
    outcome: str,
    will_retry: bool,
    response_status_code: int | None = None,
    response_payload: dict[str, Any] | None = None,
    error: str | None = None,
    error_type: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "attempt": attempt,
        "outcome": outcome,
        "will_retry": will_retry,
    }
    if response_status_code is not None:
        entry["response_status_code"] = response_status_code
    if response_payload is not None:
        entry["response_payload"] = response_payload
    if error:
        entry["error"] = error
    if error_type:
        entry["error_type"] = error_type
    return entry


def _attach_attempt_history(
    *,
    provider_payload: dict[str, Any],
    request_url: str,
    request_payload: dict[str, Any],
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = dict(provider_payload)
    payload["dispatch_meta"] = {
        "request_url": request_url,
        "request_payload": request_payload,
        "attempts": attempts,
    }
    return payload


def _is_retryable_request_exception(exc: requests.RequestException) -> bool:
    return isinstance(exc, (requests.ConnectionError, requests.ConnectTimeout))


def _is_retryable_http_response(*, response_status_code: int, provider_payload: dict[str, Any]) -> bool:
    if response_status_code not in _RETRYABLE_HTTP_STATUS_CODES:
        return False
    if provider_payload.get("status") is False:
        return False
    return True


def _build_failure_result(
    *,
    detail: str,
    request_url: str,
    request_payload: dict[str, Any],
    response_status_code: int | None,
    response_payload: dict[str, Any],
    attempts: list[dict[str, Any]] | None = None,
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
            "attempts": attempts or [],
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
            "provider": MESSAGING_PROVIDER_WABLAS,
            "status": "failed",
            "detail": "Konfigurasi provider Wablas belum lengkap.",
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
    max_attempts = _retry_attempts()
    attempts: list[dict[str, Any]] = []
    last_failure: ContactMessageDispatchResult | None = None

    for attempt_number in range(1, max_attempts + 1):
        try:
            response, provider_payload = post_form(
                url=request_url,
                payload=payload_item,
                headers={"Authorization": _wablas_authorization_header()},
                timeout_seconds=request_timeout(getattr(settings, "wablas_timeout_seconds", 15), 15),
            )
        except requests.RequestException as exc:
            should_retry = attempt_number < max_attempts and _is_retryable_request_exception(exc)
            attempts.append(
                _build_attempt_entry(
                    attempt=attempt_number,
                    outcome="request_exception",
                    will_retry=should_retry,
                    error=str(exc),
                    error_type=exc.__class__.__name__,
                )
            )
            last_failure = _build_failure_result(
                detail="Koneksi ke provider Wablas gagal.",
                request_url=request_url,
                request_payload=request_payload_snapshot,
                response_status_code=None,
                response_payload={"error": str(exc)},
                attempts=attempts,
            )
            if should_retry:
                time.sleep(_build_retry_delay(attempt_number))
                continue
            return last_failure

        current_request_url = str(response.url or request_url)
        if not response.ok:
            should_retry = (
                attempt_number < max_attempts
                and _is_retryable_http_response(
                    response_status_code=response.status_code,
                    provider_payload=provider_payload,
                )
            )
            attempts.append(
                _build_attempt_entry(
                    attempt=attempt_number,
                    outcome="http_error",
                    will_retry=should_retry,
                    response_status_code=response.status_code,
                    response_payload=provider_payload,
                )
            )
            provider_message = _provider_message(provider_payload)
            detail = (
                provider_message
                if provider_message
                else f"Provider Wablas merespons HTTP {response.status_code}."
            )
            last_failure = _build_failure_result(
                detail=detail,
                request_url=current_request_url,
                request_payload=request_payload_snapshot,
                response_status_code=response.status_code,
                response_payload=provider_payload,
                attempts=attempts,
            )
            if should_retry:
                time.sleep(_build_retry_delay(attempt_number))
                continue
            return last_failure

        if provider_payload.get("status") is False:
            attempts.append(
                _build_attempt_entry(
                    attempt=attempt_number,
                    outcome="provider_rejected",
                    will_retry=False,
                    response_status_code=response.status_code,
                    response_payload=provider_payload,
                )
            )
            provider_message = _provider_message(provider_payload)
            detail = provider_message if provider_message else "Provider Wablas menolak request pengiriman."
            return _build_failure_result(
                detail=detail,
                request_url=current_request_url,
                request_payload=request_payload_snapshot,
                response_status_code=response.status_code,
                response_payload=provider_payload,
                attempts=attempts,
            )

        dispatch_status = _extract_status(provider_payload)
        if dispatch_status == "failed":
            attempts.append(
                _build_attempt_entry(
                    attempt=attempt_number,
                    outcome="provider_failed",
                    will_retry=False,
                    response_status_code=response.status_code,
                    response_payload={
                        "status": provider_payload.get("status"),
                        "message": provider_payload.get("message"),
                        "data": provider_payload.get("data"),
                    },
                )
            )
            provider_message = _provider_message(provider_payload)
            detail = provider_message if provider_message else "Provider Wablas gagal memproses pengiriman."
            return _build_failure_result(
                detail=detail,
                request_url=current_request_url,
                request_payload=request_payload_snapshot,
                response_status_code=response.status_code,
                response_payload=provider_payload,
                attempts=attempts,
            )

        attempts.append(
            _build_attempt_entry(
                attempt=attempt_number,
                outcome="success",
                will_retry=False,
                response_status_code=response.status_code,
                response_payload={
                    "status": provider_payload.get("status"),
                    "message": provider_payload.get("message"),
                    "data": provider_payload.get("data"),
                },
            )
        )
        provider_payload = _attach_attempt_history(
            provider_payload=provider_payload,
            request_url=current_request_url,
            request_payload=request_payload_snapshot,
            attempts=attempts,
        )
        break
    else:
        return last_failure or _build_failure_result(
            detail="Provider Wablas gagal memproses pengiriman.",
            request_url=request_url,
            request_payload=request_payload_snapshot,
            response_status_code=None,
            response_payload={"error": "wablas_retry_exhausted"},
            attempts=attempts,
        )

    detail = (
        "Pesan WhatsApp berhasil diteruskan ke grup testing Wablas."
        if use_group_target and dispatch_status == "sent"
        else "Pesan WhatsApp berhasil diteruskan ke karyawan."
        if dispatch_status == "sent"
        else "Pesan WhatsApp sudah diterima Wablas untuk grup testing dan sedang diproses."
        if use_group_target and dispatch_status == "accepted"
        else "Pesan WhatsApp sudah diterima Wablas dan sedang diproses."
        if dispatch_status == "accepted"
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
