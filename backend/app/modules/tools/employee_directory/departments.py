import re


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


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def _department_alias_terms(canonical_department: str) -> set[str]:
    canonical = normalize_department(canonical_department)
    if not canonical:
        return set()

    terms = set(re.findall(r"[a-z0-9]+", _normalize_text(canonical)))
    for alias, alias_canonical in _DEPARTMENT_ALIAS_MAP.items():
        if alias_canonical == canonical:
            terms.update(re.findall(r"[a-z0-9]+", _normalize_text(alias)))
    return terms


def normalize_department(value: str) -> str:
    normalized = _normalize_text(value)
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


def department_matches(value: str, expected_department: str) -> bool:
    expected = normalize_department(expected_department)
    if not expected:
        return False
    return normalize_department(value) == expected


def strip_department_terms(value: str, expected_department: str) -> str:
    department_terms = _department_alias_terms(expected_department)
    if not department_terms:
        return str(value or "").strip()

    tokens = re.findall(r"[A-Za-z0-9]+", str(value or ""))
    kept_tokens = [
        token
        for token in tokens
        if token.lower() not in department_terms
    ]
    return " ".join(kept_tokens).strip()
