from __future__ import annotations

from modules.tools.employee_directory import repository
from modules.tools.employee_directory.schemas import EmployeeRecord


DEFAULT_SEARCH_LIMIT = 3


def list_employees() -> list[EmployeeRecord]:
    return repository.list_employees()


def find_by_id(employee_id: int | str | None) -> EmployeeRecord | None:
    return repository.find_by_id(employee_id)


def search_employees(
    query: str,
    department_hint: str = "",
    *,
    limit: int | None = None,
) -> list[EmployeeRecord]:
    return repository.search_employees(
        query,
        department_hint=department_hint,
        limit=limit if limit is not None else DEFAULT_SEARCH_LIMIT,
    )
