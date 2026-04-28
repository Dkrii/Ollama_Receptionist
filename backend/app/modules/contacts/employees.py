from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

from config import settings
from modules.knowledge_base.documents import list_documents, read_document


_PHONE_PATTERN = re.compile(r"\+?[0-9][0-9\s\-()]{7,}[0-9]")
_SOFT_SPLIT_PATTERN = re.compile(r"\s*(?:\||;|•|/|,|\u2022|\t)\s*")
_BULLET_PREFIX_PATTERN = re.compile(r"^\s*(?:[-*•\u2022]|\d+[.)-]?)\s*")


def _normalize(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _normalize_phone(value: str) -> str:
    cleaned = _normalize(value)
    if not cleaned:
        return ""

    match = _PHONE_PATTERN.search(cleaned)
    if not match:
        return ""

    phone = match.group(0)
    phone = re.sub(r"\s+", "", phone)
    phone = phone.replace("(", "").replace(")", "")
    return phone


def _looks_like_table_separator(columns: list[str]) -> bool:
    if not columns:
        return False
    return all(set(_normalize(value)) <= {"-", ":", " "} for value in columns)


def _drop_index_column(columns: list[str]) -> list[str]:
    if not columns:
        return columns
    first = _normalize(columns[0])
    if first.isdigit() and len(first) <= 4:
        return columns[1:]
    return columns


def _extract_from_columns(columns: list[str]) -> dict | None:
    if len(columns) < 4:
        return None

    cleaned_columns = [_normalize(value) for value in columns if _normalize(value)]
    cleaned_columns = _drop_index_column(cleaned_columns)
    if len(cleaned_columns) < 4:
        return None

    phone_index = -1
    phone_value = ""
    for index, value in enumerate(cleaned_columns):
        normalized_phone = _normalize_phone(value)
        if normalized_phone:
            phone_index = index
            phone_value = normalized_phone
            break

    if phone_index < 0:
        return None

    text_fields = [value for idx, value in enumerate(cleaned_columns) if idx != phone_index]
    if len(text_fields) < 3:
        return None

    nama, departemen, jabatan = text_fields[:3]
    if not (nama and departemen and jabatan and phone_value):
        return None

    return {
        "nama": nama,
        "departemen": departemen,
        "jabatan": jabatan,
        "nomor_wa": phone_value,
    }


def _sanitize_parts(parts: list[str]) -> list[str]:
    cleaned: list[str] = []
    for part in parts:
        value = _normalize(part)
        value = _BULLET_PREFIX_PATTERN.sub("", value)
        value = _normalize(value)
        if not value:
            continue
        if _normalize_phone(value):
            continue
        cleaned.append(value)
    return cleaned


def _looks_like_person_name(value: str) -> bool:
    normalized = _normalize(value)
    if not normalized:
        return False
    if any(char.isdigit() for char in normalized):
        return False
    if "@" in normalized or "http" in normalized.lower():
        return False

    tokens = [token for token in re.split(r"\s+", normalized) if token]
    if len(tokens) < 2 or len(tokens) > 5:
        return False

    alpha_tokens = [token for token in tokens if re.search(r"[a-zA-Z]", token)]
    if len(alpha_tokens) < len(tokens):
        return False

    return True


def _is_probable_employee(row: dict) -> bool:
    nama = _normalize(str(row.get("nama", "")))
    departemen = _normalize(str(row.get("departemen", "")))
    jabatan = _normalize(str(row.get("jabatan", "")))
    nomor_wa = _normalize(str(row.get("nomor_wa", "")))

    if not (_looks_like_person_name(nama) and departemen and jabatan and nomor_wa):
        return False
    if any(marker in value.lower() for marker in ("@", "http", "www") for value in (departemen, jabatan)):
        return False
    if len(departemen) > 50 or len(jabatan) > 70:
        return False
    return True


def _parts_from_freeform_text(text: str) -> list[str]:
    normalized = _normalize(text)
    if not normalized:
        return []

    without_phone = _PHONE_PATTERN.sub(" | ", normalized)
    seeded_parts = _SOFT_SPLIT_PATTERN.split(without_phone)
    parts = _sanitize_parts(seeded_parts)
    if len(parts) >= 3:
        return parts

    # fallback split on long dash separators when soft delimiters are absent
    dash_parts = re.split(r"\s+-\s+", without_phone)
    return _sanitize_parts(dash_parts)


def _extract_from_freeform_line(line: str) -> dict | None:
    phone = _normalize_phone(line)
    if not phone:
        return None

    parts = _parts_from_freeform_text(line)
    if len(parts) < 3:
        return None

    return {
        "nama": parts[0],
        "departemen": parts[1],
        "jabatan": parts[2],
        "nomor_wa": phone,
    }


def _extract_from_line_window(lines: list[str], index: int) -> dict | None:
    current = _normalize(lines[index] if 0 <= index < len(lines) else "")
    if not current:
        return None

    phone = _normalize_phone(current)
    if not phone:
        return None

    # Window mode is only for multi-line records where current line is mostly phone number.
    residual = _normalize(_PHONE_PATTERN.sub("", current))
    if residual:
        return None

    window_parts: list[str] = []
    for back in (3, 2, 1):
        pointer = index - back
        if pointer < 0:
            continue
        candidate = _normalize(lines[pointer])
        if not candidate:
            continue
        if _normalize_phone(candidate):
            continue
        window_parts.append(candidate)
    window_parts.append(current)

    merged = " | ".join(window_parts)
    parts = _parts_from_freeform_text(merged)
    if len(parts) < 3:
        return None

    return {
        "nama": parts[0],
        "departemen": parts[1],
        "jabatan": parts[2],
        "nomor_wa": phone,
    }


def _append_unique(employees: list[dict], seen: set[tuple[str, str, str, str]], row: dict | None) -> None:
    if not row:
        return
    if not _is_probable_employee(row):
        return

    key = (
        row["nama"].lower(),
        row["departemen"].lower(),
        row["jabatan"].lower(),
        row["nomor_wa"],
    )
    if key in seen:
        return

    seen.add(key)
    employees.append(row)


def _parse_employee_table_rows(lines: list[str]) -> list[dict]:
    employees: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()

    for index, raw_line in enumerate(lines):
        line = _normalize(raw_line)
        if not line:
            continue

        if "|" in line:
            columns = [part.strip() for part in line.split("|") if part.strip()]
            if _looks_like_table_separator(columns):
                continue
            _append_unique(employees, seen, _extract_from_columns(columns))
            continue

        _append_unique(employees, seen, _extract_from_freeform_line(line))
        _append_unique(employees, seen, _extract_from_line_window(lines, index))

    return employees


def _employee_documents() -> list[Path]:
    documents = list_documents(settings.knowledge_dir)
    return [path for path in documents if path.suffix.lower() in {".docx", ".pdf"}]


@lru_cache(maxsize=8)
def _load_employee_directory_cached(signature: tuple[tuple[str, int, int], ...]) -> list[dict]:
    employees: list[dict] = []

    for relative_path, _, _ in signature:
        absolute_path = settings.knowledge_dir / relative_path
        if not absolute_path.exists():
            continue

        text = read_document(absolute_path)
        rows = _parse_employee_table_rows(text.splitlines())

        unique_rows_by_key: dict[tuple[str, str, str, str], dict] = {}
        for row in rows:
            key = (
                _normalize(row.get("nama", "")).lower(),
                _normalize(row.get("departemen", "")).lower(),
                _normalize(row.get("jabatan", "")).lower(),
                _normalize(row.get("nomor_wa", "")),
            )
            unique_rows_by_key[key] = row

        if len(unique_rows_by_key) < 2:
            continue

        for row in unique_rows_by_key.values():
            employees.append({
                "nama": row["nama"],
                "departemen": row["departemen"],
                "jabatan": row["jabatan"],
                "nomor_wa": row["nomor_wa"],
                "source": relative_path,
            })

    employees.sort(key=lambda item: _normalize(item.get("nama", "")).lower())

    for idx, employee in enumerate(employees, start=1):
        employee["id"] = idx

    return employees


def load_employee_directory() -> list[dict]:
    docs = _employee_documents()
    signature = tuple(
        (
            str(path.relative_to(settings.knowledge_dir)),
            int(path.stat().st_mtime),
            int(path.stat().st_size),
        )
        for path in docs
    )
    return list(_load_employee_directory_cached(signature))
