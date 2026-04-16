import re

from .core import _normalize_message


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
