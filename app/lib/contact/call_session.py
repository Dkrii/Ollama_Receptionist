import uuid
from typing import Any

from config import settings


CALL_PROVIDER_DUMMY = "dummy"
CALL_PROVIDER_TWILIO = "twilio_voice"
ACTIVE_CALL_STATUSES = {"preparing", "dialing_employee", "ringing", "connected"}


def is_call_simulation() -> bool:
    return str(getattr(settings, "app_env", "development") or "development").strip().lower() != "production"


def call_provider() -> str:
    return CALL_PROVIDER_DUMMY if is_call_simulation() else CALL_PROVIDER_TWILIO


def create_call_session_id() -> str:
    return uuid.uuid4().hex


def build_dev_identity(call_session_id: str) -> str:
    return f"dev-call-{str(call_session_id or '').strip()}"


def mask_value(value: str | None, *, head: int = 4, tail: int = 4) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    if len(text) <= (head + tail):
        return text
    return f"{text[:head]}...{text[-tail:]}"


def public_url(path: str) -> str:
    base_url = str(getattr(settings, "app_url", "") or "").strip().rstrip("/")
    clean_path = "/" + str(path or "").lstrip("/")
    if not base_url:
        raise RuntimeError("APP_URL wajib diisi untuk telepon production.")
    return f"{base_url}{clean_path}"


def require_employee_phone(employee: dict[str, Any]) -> str:
    phone = str(employee.get("nomor_wa") or "").strip()
    if not phone:
        raise RuntimeError("Nomor telepon karyawan belum tersedia.")
    return phone


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
    normalized = str(status or "").strip().lower()
    if normalized == "preparing":
        return f"Saya sedang menyiapkan sambungan telepon ke {employee_name}."
    if normalized == "dialing_employee":
        return f"Saya sedang menghubungi {employee_name}."
    if normalized == "ringing":
        return f"{employee_name} sedang dipanggil."
    if normalized == "connected":
        return f"Sambungan dengan {employee_name} sudah aktif."
    if normalized == "busy":
        return f"{employee_name} sedang sibuk."
    if normalized == "no_response":
        return f"{employee_name} belum menjawab panggilan."
    if normalized == "completed":
        return f"Panggilan dengan {employee_name} sudah selesai."
    return f"Panggilan ke {employee_name} belum berhasil diproses."


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
