import re
from typing import Any

from shared.utils.text import normalize_text_lower


_DEPARTMENT_ALIAS_MAP: dict[str, str] = {
    "it": "IT",
    "ti": "IT",
    "teknologi informasi": "IT",
    "informatika": "IT",
    "sistem": "IT",
    "komputer": "IT",
    "teknis": "IT",
    "information technology": "IT",
    "hr": "HR",
    "hrd": "HR",
    "human resource": "HR",
    "human resources": "HR",
    "human capital": "HR",
    "hc": "HR",
    "sdm": "HR",
    "sumber daya manusia": "HR",
    "personalia": "HR",
    "kepegawaian": "HR",
    "finance": "Finance",
    "keuangan": "Finance",
    "akuntansi": "Finance",
    "accounting": "Finance",
    "akunting": "Finance",
    "marketing": "Marketing",
    "pemasaran": "Marketing",
    "promosi": "Marketing",
    "ga": "GA",
    "general affairs": "GA",
    "general affair": "GA",
    "umum": "GA",
    "bagian umum": "GA",
    "legal": "Legal",
    "hukum": "Legal",
    "procurement": "Procurement",
    "pengadaan": "Procurement",
    "produksi": "Produksi",
    "production": "Produksi",
    "operasional": "Operasional",
    "operations": "Operasional",
    "security": "Security",
    "keamanan": "Security",
    "satpam": "Security",
}

KNOWN_DEPARTMENTS: set[str] = set(_DEPARTMENT_ALIAS_MAP.values())

_YES_PATTERNS = (
    r"\bya\b",
    r"\biya\b",
    r"\byes\b",
    r"\bok(?:e)?\b",
    r"\bsetuju\b",
    r"\bbetul\b",
    r"\blanjut\b",
    r"\bboleh\b",
    r"\bsilakan\b",
)
_NO_PATTERNS = (
    r"\btidak\b",
    r"\bnggak\b",
    r"\bga\b",
    r"\bgak\b",
    r"\bno\b",
    r"\bbatal\b",
    r"\bjangan\b",
    r"\btidak jadi\b",
    r"\bga usah\b",
    r"\bnggak usah\b",
)
_CANCEL_PATTERNS = (
    r"^\s*(?:batal|batalkan|tidak jadi|nggak jadi|ga jadi|gak jadi|ga usah|gak usah|nggak usah|jangan jadi)\s*$",
)
_CONTINUE_PATTERNS = (
    r"^\s*(?:lanjut|lanjutkan|teruskan|oke lanjut|ok lanjut|ya lanjut|silakan lanjut)\s*$",
)
_NAME_PREFIX_PATTERNS = (
    r"^(?:nama saya|saya bernama|perkenalkan saya)\s+(.+)$",
    r"^(?:ini|saya)\s+([a-z][a-z .'-]{1,60})$",
)
_NAME_INVALID_PREFIXES = {
    "ya",
    "iya",
    "yes",
    "ok",
    "oke",
    "tidak",
    "nggak",
    "gak",
    "ga",
    "no",
    "batal",
    "halo",
    "hai",
    "hello",
    "selamat",
    "pagi",
    "siang",
    "sore",
    "malam",
    "permisi",
    "terima",
    "kasih",
    "mau",
    "ingin",
    "perlu",
    "butuh",
    "dari",
    "hubungi",
    "menghubungi",
    "ketemu",
    "bertemu",
    "tanya",
    "menanyakan",
    "cari",
    "carikan",
    "titip",
    "pesan",
}
_GOAL_INVALID_PATTERNS = (
    r"^\b(?:ya|iya|oke|ok|lanjut|lanjutkan|tidak|nggak|ga|batal)\b$",
    r"^\b(?:nama saya|saya bernama|perkenalkan saya)\b",
    r"^\b(?:terima kasih|makasih|thanks|thx|halo|hai|permisi|selamat pagi|selamat siang|selamat sore|selamat malam)\b$",
)


def _normalize_message(message: str) -> str:
    return " ".join((message or "").lower().split())


def _matches_any_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def normalize_department(value: str) -> str:
    normalized = _normalize_message(value)
    if not normalized:
        return ""

    if normalized in _DEPARTMENT_ALIAS_MAP:
        return _DEPARTMENT_ALIAS_MAP[normalized]

    for alias, canonical in _DEPARTMENT_ALIAS_MAP.items():
        if re.search(rf"\b{re.escape(alias)}\b", normalized):
            return canonical

    compact = normalized.replace(" ", "")
    if compact in {"it", "hr", "hrd", "hc", "ga"}:
        return _DEPARTMENT_ALIAS_MAP.get(compact, compact.upper())

    return str(value or "").strip()


def extract_department_from_text(text: str) -> str | None:
    normalized = _normalize_message(text)
    if not normalized:
        return None

    dept_prefix_pattern = re.compile(
        r"(?:dari|bagian|tim|divisi|departemen|unit|bidang)\s+(\S+(?:\s+\S+)?)",
        re.IGNORECASE,
    )
    match = dept_prefix_pattern.search(normalized)
    if match:
        candidate = match.group(1).strip()
        canonical = normalize_department(candidate)
        if canonical and canonical in KNOWN_DEPARTMENTS:
            return canonical

    for alias, canonical in sorted(_DEPARTMENT_ALIAS_MAP.items(), key=lambda item: -len(item[0])):
        if re.search(rf"\b{re.escape(alias)}\b", normalized):
            return canonical

    return None


def normalize_contact_mode(value: str | None) -> str:
    mode = str(value or "auto").strip().lower()
    if mode in {"call", "notify", "auto"}:
        return mode
    return "auto"


def classify_confirmation_reply(message: str) -> str:
    normalized = normalize_text_lower(message)
    if not normalized:
        return "unknown"

    has_yes = _matches_any_pattern(normalized, _YES_PATTERNS)
    has_no = _matches_any_pattern(normalized, _NO_PATTERNS)

    if has_yes and not has_no:
        return "confirm_yes"
    if has_no and not has_yes:
        return "confirm_no"
    return "unknown"


def is_cancel_message(message: str) -> bool:
    normalized = normalize_text_lower(message)
    return bool(normalized and _matches_any_pattern(normalized, _CANCEL_PATTERNS))


def is_continue_message(message: str) -> bool:
    normalized = normalize_text_lower(message)
    return bool(normalized and _matches_any_pattern(normalized, _CONTINUE_PATTERNS))


def _clean_name_candidate(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z .'-]", " ", str(value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .'-")
    return cleaned


def _is_plausible_name(value: str, selected_name: str = "") -> bool:
    cleaned = _clean_name_candidate(value)
    if not cleaned:
        return False

    lowered = cleaned.lower()
    tokens = [token for token in re.findall(r"[a-z]+", lowered) if token]
    if not tokens or len(tokens) > 4:
        return False
    if any(token in _NAME_INVALID_PREFIXES for token in tokens):
        return False

    if selected_name and lowered == selected_name.strip().lower():
        return False

    return True


def extract_visitor_name(message: str, *, selected_name: str = "") -> str:
    normalized = (message or "").strip()
    if not normalized:
        return ""

    for pattern in _NAME_PREFIX_PATTERNS:
        match = re.match(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = _clean_name_candidate(match.group(1))
        if _is_plausible_name(candidate, selected_name=selected_name):
            return candidate

    direct_candidate = _clean_name_candidate(normalized)
    if _is_plausible_name(direct_candidate, selected_name=selected_name):
        return direct_candidate

    return ""


def extract_visitor_goal(message: str) -> str:
    normalized = re.sub(r"\s+", " ", str(message or "").strip())
    if len(normalized) < 8:
        return ""

    lowered = normalized.lower()
    if any(re.search(pattern, lowered) for pattern in _GOAL_INVALID_PATTERNS):
        return ""

    return normalized


def normalize_pending_action(raw_value: Any) -> dict[str, Any] | None:
    if not isinstance(raw_value, dict):
        return None
    if str(raw_value.get("type") or "").strip().lower() != "contact_message":
        return None

    target_employee_id = raw_value.get("target_employee_id")
    try:
        normalized_target_id = int(target_employee_id) if target_employee_id is not None and target_employee_id != "" else None
    except Exception:
        normalized_target_id = None

    candidates = raw_value.get("candidates")
    if not isinstance(candidates, list):
        candidates = []

    return {
        "type": "contact_message",
        "target_employee_id": normalized_target_id,
        "target_label": str(raw_value.get("target_label") or "").strip(),
        "confirmed": bool(raw_value.get("confirmed") is True),
        "visitor_name": str(raw_value.get("visitor_name") or "").strip(),
        "visitor_goal": str(raw_value.get("visitor_goal") or "").strip(),
        "target_kind": str(raw_value.get("target_kind") or "person").strip().lower(),
        "target_department": str(raw_value.get("target_department") or "").strip(),
        "candidates": candidates,
    }


def build_flow_state(pending_action: dict[str, Any] | None) -> dict[str, Any]:
    return {"pending_action": normalize_pending_action(pending_action)}
