from __future__ import annotations

import logging
import re
import time
from typing import Any

from infrastructure import database
from modules.tools.employee_directory.schemas import EmployeeRecord


_logger = logging.getLogger(__name__)

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PHONE_CLEANUP_PATTERN = re.compile(r"[\s().-]+")

CONNECTION_ALIAS = "postgres"
CACHE_TTL_SECONDS = 60

EMPLOYEE_TABLE = "employees"
EMPLOYEE_ID_COLUMN = "id"
EMPLOYEE_NAME_COLUMN = "nama"
EMPLOYEE_DEPARTMENT_COLUMN = "departemen"
EMPLOYEE_POSITION_COLUMN = "jabatan"
EMPLOYEE_PHONE_COLUMN = "nomor_wa"

_cached_rows: list[EmployeeRecord] | None = None
_cache_expires_at = 0.0


def _safe_identifier(value: str, *, label: str) -> str:
    raw_value = str(value or "").strip()
    parts = raw_value.split(".")
    if not raw_value or not all(_IDENTIFIER_PATTERN.fullmatch(part or "") for part in parts):
        raise ValueError(f"Invalid employee database {label}: {raw_value!r}")
    return ".".join(parts)


def _select_query() -> str:
    table = _safe_identifier(EMPLOYEE_TABLE, label="table")
    id_column = _safe_identifier(EMPLOYEE_ID_COLUMN, label="id column")
    name_column = _safe_identifier(EMPLOYEE_NAME_COLUMN, label="name column")
    department_column = _safe_identifier(EMPLOYEE_DEPARTMENT_COLUMN, label="department column")
    position_column = _safe_identifier(EMPLOYEE_POSITION_COLUMN, label="position column")
    phone_column = _safe_identifier(EMPLOYEE_PHONE_COLUMN, label="phone column")

    return f"""
SELECT
  {id_column} AS id,
  {name_column} AS nama,
  {department_column} AS departemen,
  {position_column} AS jabatan,
  {phone_column} AS nomor_wa
FROM {table}
ORDER BY {name_column}
""".strip()


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_phone(value: Any) -> str:
    cleaned = _normalize_text(value)
    if not cleaned:
        return ""
    return _PHONE_CLEANUP_PATTERN.sub("", cleaned)


def _normalize_employee_row(row: dict[str, Any]) -> EmployeeRecord | None:
    try:
        employee_id = int(str(row.get("id", "")).strip())
    except Exception:
        return None

    name = _normalize_text(row.get("nama"))
    department = _normalize_text(row.get("departemen"))
    position = _normalize_text(row.get("jabatan"))
    phone = _normalize_phone(row.get("nomor_wa"))

    if not name or not phone:
        return None

    return {
        "id": employee_id,
        "nama": name,
        "departemen": department,
        "jabatan": position,
        "nomor_wa": phone,
        "source": "database",
    }


def _copy_rows(rows: list[EmployeeRecord]) -> list[EmployeeRecord]:
    return [dict(row) for row in rows]


def clear_cache() -> None:
    global _cached_rows, _cache_expires_at
    _cached_rows = None
    _cache_expires_at = 0.0


def list_employees() -> list[EmployeeRecord]:
    global _cached_rows, _cache_expires_at

    now = time.monotonic()
    if _cached_rows is not None and now < _cache_expires_at:
        return _copy_rows(_cached_rows)

    try:
        rows = database.fetch_all(_select_query(), alias=CONNECTION_ALIAS)
    except database.DatabaseConfigurationError as exc:
        _logger.warning("employee_directory database is not configured: %s", exc)
        return []
    except Exception:
        _logger.exception("employee_directory database query failed")
        return []

    employees: list[EmployeeRecord] = []
    seen_ids: set[int] = set()
    for row in rows:
        employee = _normalize_employee_row(row)
        if not employee or employee["id"] in seen_ids:
            continue
        seen_ids.add(employee["id"])
        employees.append(employee)

    employees.sort(key=lambda item: item["nama"].lower())

    _cached_rows = _copy_rows(employees)
    _cache_expires_at = now + max(0, CACHE_TTL_SECONDS)
    return _copy_rows(employees)


def find_by_id(employee_id: int | str | None) -> EmployeeRecord | None:
    try:
        normalized_id = int(str(employee_id or "").strip())
    except Exception:
        return None

    for employee in list_employees():
        if employee["id"] == normalized_id:
            return employee
    return None


def _search_blob(employee: EmployeeRecord) -> str:
    return " ".join(
        [
            employee.get("nama", ""),
            employee.get("departemen", ""),
            employee.get("jabatan", ""),
        ]
    ).lower()


def search_employees(query: str, department_hint: str = "") -> list[EmployeeRecord]:
    normalized_query = _normalize_text(query).lower()
    normalized_department = _normalize_text(department_hint).lower()

    employees = list_employees()
    if not normalized_query and not normalized_department:
        return employees

    matches: list[EmployeeRecord] = []
    for employee in employees:
        blob = _search_blob(employee)
        department = employee.get("departemen", "").lower()
        if normalized_department and normalized_department not in department:
            continue
        if normalized_query and normalized_query not in blob:
            continue
        matches.append(employee)
    return matches
