"""
Shared helpers to normalize department names consistently.
"""

import re


# Alias -> canonical. Tambahkan entri baru di sini saja.
_ALIAS_MAP: dict[str, str] = {
    # IT
    "it": "IT",
    "ti": "IT",
    "teknologi informasi": "IT",
    "informatika": "IT",
    "sistem": "IT",
    "komputer": "IT",
    "teknis": "IT",
    "information technology": "IT",
    # HR
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
    # Finance
    "finance": "Finance",
    "keuangan": "Finance",
    "akuntansi": "Finance",
    "accounting": "Finance",
    "akunting": "Finance",
    # Marketing
    "marketing": "Marketing",
    "pemasaran": "Marketing",
    "promosi": "Marketing",
    # General Affairs / GA
    "ga": "GA",
    "general affairs": "GA",
    "general affair": "GA",
    "umum": "GA",
    "bagian umum": "GA",
    # Legal
    "legal": "Legal",
    "hukum": "Legal",
    # Procurement
    "procurement": "Procurement",
    "pengadaan": "Procurement",
    # Production / Operations
    "produksi": "Produksi",
    "production": "Produksi",
    "operasional": "Operasional",
    "operations": "Operasional",
    # Security
    "security": "Security",
    "keamanan": "Security",
    "satpam": "Security",
}

# Daftar semua canonical department names (digunakan untuk deteksi)
KNOWN_DEPARTMENTS: set[str] = set(_ALIAS_MAP.values())


def normalize_department(value: str) -> str:
    """
    Kembalikan nama departemen dalam bentuk canonical.

    Contoh:
        "teknologi informasi" -> "IT"
        "HRD"                 -> "HR"
        "human capital"        -> "HR"
        "Produksi"            -> "Produksi"
    """
    normalized = " ".join((value or "").lower().split())
    if not normalized:
        return ""

    # Coba full match dulu (multi-word aliases)
    if normalized in _ALIAS_MAP:
        return _ALIAS_MAP[normalized]

    # Pattern match (untuk partial)
    for alias, canonical in _ALIAS_MAP.items():
        if re.search(rf"\b{re.escape(alias)}\b", normalized):
            return canonical

    compact = normalized.replace(" ", "")
    if compact in {"it", "hr", "hrd", "hc", "ga"}:
        return _ALIAS_MAP.get(compact, compact.upper())

    return value.strip()


def extract_department_from_text(text: str) -> str | None:
    """
    Coba ekstrak nama departemen dari teks bebas.

    Mengembalikan canonical department jika ditemukan, None jika tidak.
    Berguna untuk mendeteksi "Budi dari IT" -> "IT"
    """
    normalized = " ".join((text or "").lower().split())
    if not normalized:
        return None

    # Cek pola "dari <dept>", "bagian <dept>", "tim <dept>", "divisi <dept>"
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

    # Cek apakah text mengandung nama departemen langsung
    for alias, canonical in sorted(_ALIAS_MAP.items(), key=lambda x: -len(x[0])):
        if re.search(rf"\b{re.escape(alias)}\b", normalized):
            return canonical

    return None
