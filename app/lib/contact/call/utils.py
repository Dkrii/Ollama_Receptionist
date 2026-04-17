import uuid

from config import settings


ACTIVE_CALL_STATUSES = {"preparing", "dialing_employee", "ringing", "connected"}


def create_call_session_id() -> str:
    return uuid.uuid4().hex


def build_dev_identity(call_session_id: str) -> str:
    return f"dev-call-{str(call_session_id or '').strip()}"


def mask_contact_value(value: str | None, *, head: int = 4, tail: int = 4) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    if len(text) <= (head + tail):
        return text
    return f"{text[:head]}...{text[-tail:]}"


def build_call_status_detail(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "preparing":
        return "Menyiapkan sambungan."
    if normalized == "dialing_employee":
        return "Menghubungi."
    if normalized == "ringing":
        return "Berdering."
    if normalized == "connected":
        return "Terhubung."
    if normalized == "busy":
        return "Sedang sibuk."
    if normalized == "no_response":
        return "Tidak merespons."
    if normalized == "completed":
        return "Panggilan selesai."
    return "Tidak terhubung."


def public_url(path: str) -> str:
    base_url = str(getattr(settings, "app_url", "") or "").strip().rstrip("/")
    clean_path = "/" + str(path or "").lstrip("/")
    if not base_url:
        raise RuntimeError("APP_URL wajib diisi untuk telepon production.")
    return f"{base_url}{clean_path}"
