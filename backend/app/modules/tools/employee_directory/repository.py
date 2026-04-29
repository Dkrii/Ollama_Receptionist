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

CONNECTION_ALIAS = "mssql"
CACHE_TTL_SECONDS = 60
SEARCH_LIMIT = 20

EMPLOYEE_TABLE = "dbo.VIEW_EMP_DEPT"
EMPLOYEE_ID_COLUMN = "emp_no"
EMPLOYEE_NAME_COLUMN = "full_name"
EMPLOYEE_DIVISION_COLUMN = "Division_Name"
EMPLOYEE_DEPARTMENT_COLUMN = "Department_Name"
EMPLOYEE_SECTION_COLUMN = "Section_Name"
EMPLOYEE_POSITION_COLUMN = "Position_Name"
EMPLOYEE_PHONE_COLUMN = "phone"
EMPLOYEE_END_DATE_COLUMN = "end_date"

_SEARCH_STOPWORDS = {
    "ada",
    "akan",
    "aku",
    "anda",
    "atau",
    "bagian",
    "bapak",
    "bu",
    "buat",
    "butuh",
    "cari",
    "carikan",
    "dari",
    "dengan",
    "departemen",
    "divisi",
    "hubungi",
    "ibu",
    "ingin",
    "ke",
    "kontak",
    "mau",
    "mbak",
    "mohon",
    "pak",
    "pesan",
    "sama",
    "sampaikan",
    "saya",
    "team",
    "tim",
    "titip",
    "tolong",
    "untuk",
}

_cached_rows: list[EmployeeRecord] | None = None
_cache_expires_at = 0.0


def _safe_identifier(value: str, *, label: str) -> str:
    raw_value = str(value or "").strip()
    parts = raw_value.split(".")
    if not raw_value or not all(
        _IDENTIFIER_PATTERN.fullmatch(part or "") for part in parts
    ):
        raise ValueError(f"Invalid employee database {label}: {raw_value!r}")
    return ".".join(parts)


def _employee_columns() -> dict[str, str]:
    return {
        "table": _safe_identifier(EMPLOYEE_TABLE, label="table"),
        "id": _safe_identifier(EMPLOYEE_ID_COLUMN, label="id column"),
        "name": _safe_identifier(EMPLOYEE_NAME_COLUMN, label="name column"),
        "division": _safe_identifier(
            EMPLOYEE_DIVISION_COLUMN, label="division column"
        ),
        "department": _safe_identifier(
            EMPLOYEE_DEPARTMENT_COLUMN, label="department column"
        ),
        "section": _safe_identifier(EMPLOYEE_SECTION_COLUMN, label="section column"),
        "position": _safe_identifier(
            EMPLOYEE_POSITION_COLUMN, label="position column"
        ),
        "phone": _safe_identifier(EMPLOYEE_PHONE_COLUMN, label="phone column"),
        "end_date": _safe_identifier(
            EMPLOYEE_END_DATE_COLUMN, label="end date column"
        ),
    }


def _id_text_expression(id_column: str) -> str:
    return f"LTRIM(RTRIM(CONVERT(varchar(64), {id_column})))"


def _normalized_id_expression(id_column: str) -> str:
    id_text = _id_text_expression(id_column)
    return (
        "CASE "
        f"WHEN PATINDEX('%[^0]%', {id_text}) = 0 THEN '0' "
        f"ELSE SUBSTRING({id_text}, PATINDEX('%[^0]%', {id_text}), LEN({id_text})) "
        "END"
    )


def _active_employee_where_clause(columns: dict[str, str]) -> str:
    id_text = _id_text_expression(columns["id"])
    return f"""
WHERE {columns["name"]} IS NOT NULL
  AND {columns["phone"]} IS NOT NULL
  AND {columns["id"]} IS NOT NULL
  AND NULLIF({id_text}, '') IS NOT NULL
  AND {id_text} NOT LIKE '%[^0-9]%'
  AND {columns["end_date"]} IS NULL
""".strip()


def _select_query() -> str:
    columns = _employee_columns()
    where_clause = _active_employee_where_clause(columns)

    return f"""
SELECT
  {columns["id"]} AS id,
  {columns["name"]} AS nama,
  {columns["department"]} AS departemen,
  {columns["position"]} AS jabatan,
  {columns["phone"]} AS nomor_wa
FROM {columns["table"]}
{where_clause}
ORDER BY {columns["name"]}
""".strip()


def _find_by_id_query() -> str:
    columns = _employee_columns()
    where_clause = _active_employee_where_clause(columns)
    normalized_id = _normalized_id_expression(columns["id"])

    return f"""
SELECT TOP 1
  {columns["id"]} AS id,
  {columns["name"]} AS nama,
  {columns["department"]} AS departemen,
  {columns["position"]} AS jabatan,
  {columns["phone"]} AS nomor_wa
FROM {columns["table"]}
{where_clause}
  AND {normalized_id} = %s
ORDER BY {columns["name"]}
""".strip()


def _safe_limit(value: int | None, *, default: int = SEARCH_LIMIT) -> int:
    try:
        parsed = int(value or default)
    except Exception:
        parsed = default
    return max(1, min(parsed, 50))


def _search_terms(value: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9]+", _normalize_text(value).lower())
    terms: list[str] = []
    for token in tokens:
        if len(token) < 2 or token in _SEARCH_STOPWORDS:
            continue
        if token not in terms:
            terms.append(token)
    return terms[:6]


def _search_condition(
    columns: dict[str, str],
    terms: list[str],
    fields: list[str],
) -> tuple[str, list[str]]:
    if not terms:
        return "", []

    term_clauses: list[str] = []
    params: list[str] = []
    for term in terms:
        like_value = f"%{term}%"
        field_clauses = [f"{columns[field]} LIKE %s" for field in fields]
        term_clauses.append("(" + " OR ".join(field_clauses) + ")")
        params.extend([like_value] * len(fields))

    return "(" + " OR ".join(term_clauses) + ")", params


def _search_query(
    *,
    query_terms: list[str],
    department_terms: list[str],
    limit: int,
) -> tuple[str, tuple[str, ...]]:
    columns = _employee_columns()
    where_clause = _active_employee_where_clause(columns)

    filters: list[str] = []
    params: list[str] = []

    query_filter, query_params = _search_condition(
        columns,
        query_terms,
        ["name", "department", "position", "division", "section"],
    )
    if query_filter:
        filters.append(query_filter)
        params.extend(query_params)

    department_filter, department_params = _search_condition(
        columns,
        department_terms,
        ["department", "division", "section"],
    )
    if department_filter:
        filters.append(department_filter)
        params.extend(department_params)

    if filters:
        where_clause += "\n  AND " + "\n  AND ".join(filters)

    return (
        f"""
SELECT TOP {_safe_limit(limit)}
  {columns["id"]} AS id,
  {columns["name"]} AS nama,
  {columns["department"]} AS departemen,
  {columns["position"]} AS jabatan,
  {columns["phone"]} AS nomor_wa
FROM {columns["table"]}
{where_clause}
ORDER BY {columns["name"]}
""".strip(),
        tuple(params),
    )


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


def _normalize_employee_rows(rows: list[dict[str, Any]]) -> list[EmployeeRecord]:
    employees: list[EmployeeRecord] = []
    seen_ids: set[int] = set()
    for row in rows:
        employee = _normalize_employee_row(row)
        if not employee or employee["id"] in seen_ids:
            continue
        seen_ids.add(employee["id"])
        employees.append(employee)

    employees.sort(key=lambda item: item["nama"].lower())
    return employees


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

    employees = _normalize_employee_rows(rows)
    _cached_rows = _copy_rows(employees)
    _cache_expires_at = now + max(0, CACHE_TTL_SECONDS)
    return _copy_rows(employees)


def find_by_id(employee_id: int | str | None) -> EmployeeRecord | None:
    try:
        normalized_id = int(str(employee_id or "").strip())
    except Exception:
        return None

    try:
        rows = database.fetch_all(
            _find_by_id_query(),
            params=(str(normalized_id),),
            alias=CONNECTION_ALIAS,
        )
    except database.DatabaseConfigurationError as exc:
        _logger.warning("employee_directory database is not configured: %s", exc)
        return None
    except Exception:
        _logger.exception("employee_directory find_by_id query failed")
        return None

    employees = _normalize_employee_rows(rows)
    return employees[0] if employees else None


def search_employees(
    query: str,
    department_hint: str = "",
    *,
    limit: int | None = SEARCH_LIMIT,
) -> list[EmployeeRecord]:
    query_terms = _search_terms(query)
    department_terms = _search_terms(department_hint)
    if not query_terms and not department_terms:
        return []

    sql, params = _search_query(
        query_terms=query_terms,
        department_terms=department_terms,
        limit=_safe_limit(limit),
    )

    try:
        rows = database.fetch_all(sql, params=params, alias=CONNECTION_ALIAS)
    except database.DatabaseConfigurationError as exc:
        _logger.warning("employee_directory database is not configured: %s", exc)
        return []
    except Exception:
        _logger.exception("employee_directory search query failed")
        return []

    return _normalize_employee_rows(rows)
