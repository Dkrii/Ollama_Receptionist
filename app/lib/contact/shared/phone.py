import re
from typing import Any


_PHONE_CLEAN_PATTERN = re.compile(r"[\s\-\(\)\+]")


def require_contact_phone(employee: dict[str, Any]) -> str:
    phone = str(employee.get("nomor_wa") or "").strip()
    if not phone:
        raise RuntimeError("Nomor telepon karyawan belum tersedia.")
    return phone


def compact_phone_number(value: str | None) -> str:
    phone = _PHONE_CLEAN_PATTERN.sub("", str(value or "").strip())
    return phone.strip()


def normalize_indonesia_phone(value: str | None) -> str:
    phone = compact_phone_number(value)
    if not phone:
        return ""

    if phone.startswith("0"):
        phone = "62" + phone[1:]
    elif phone.startswith("8"):
        phone = "62" + phone

    if not phone.isdigit() or len(phone) < 10:
        return ""
    return phone


def normalize_indonesia_e164_phone(value: str | None) -> str:
    phone = normalize_indonesia_phone(value)
    if not phone:
        return ""
    return f"+{phone}"
