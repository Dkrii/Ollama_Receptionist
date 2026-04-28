import logging
import re
from difflib import SequenceMatcher

from modules.chat.nlp import normalize_department
from common.text import normalize_text_lower
from modules.contacts.employees import load_employee_directory


_logger = logging.getLogger(__name__)


def _load_employee_directory_safe() -> list[dict]:
    try:
        return load_employee_directory()
    except Exception:
        _logger.exception("chat.employee_directory failed to load")
        return []


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _normalize_department_label(value: str) -> str:
    return normalize_department(value)


def _score_employee_match(employee: dict, query: str) -> float:
    nq = normalize_text_lower(query)
    if not nq:
        return 1.0

    nama = normalize_text_lower(str(employee.get("nama", "")))
    dept = normalize_text_lower(str(employee.get("departemen", "")))
    jabatan = normalize_text_lower(str(employee.get("jabatan", "")))

    score_nama = _similarity(nq, nama)
    nama_tokens = nama.split()
    token_scores = [_similarity(nq, t) for t in nama_tokens] if nama_tokens else [0.0]
    score_token_name = max(token_scores)
    score_contains = 0.75 if nq in nama else 0.0
    score_dept = _similarity(nq, dept) * 0.65
    score_jabatan = _similarity(nq, jabatan) * 0.55

    return max(score_nama, score_token_name, score_contains, score_dept, score_jabatan)


def _find_employee_candidates(query: str, department_hint: str = "") -> list[dict]:
    employees = _load_employee_directory_safe()
    if not query or not normalize_text_lower(query):
        return employees

    canonical_hint = _normalize_department_label(department_hint)
    scored: list[tuple[dict, float]] = []
    for employee in employees:
        score = _score_employee_match(employee, query)
        employee_department = _normalize_department_label(str(employee.get("departemen", "")))
        if canonical_hint:
            if employee_department == canonical_hint:
                score += 0.35
            else:
                score -= 0.18
        scored.append((employee, score))

    if not scored:
        return []

    scored.sort(
        key=lambda item: (
            -item[1],
            normalize_text_lower(str(item[0].get("nama", ""))),
        )
    )

    top_score = float(scored[0][1])
    min_score = 0.55 if not canonical_hint else 0.40
    spread_limit = 0.18

    filtered_scored = [
        (employee, score)
        for employee, score in scored
        if score >= min_score and (top_score - score) <= spread_limit
    ]

    if not filtered_scored and top_score >= min_score:
        filtered_scored = [scored[0]]

    matches = [emp for emp, _ in filtered_scored]

    if canonical_hint:
        department_matches = [
            emp for emp in matches
            if _normalize_department_label(str(emp.get("departemen", ""))) == canonical_hint
        ]
        if department_matches:
            matches = department_matches

    return matches


def _find_department_candidates(department: str) -> list[dict]:
    canonical_dept = _normalize_department_label(department)
    if not canonical_dept:
        return []

    employees = _load_employee_directory_safe()
    matches: list[dict] = []
    for employee in employees:
        employee_department = _normalize_department_label(str(employee.get("departemen", "")))
        if employee_department == canonical_dept:
            matches.append(employee)

    matches.sort(key=lambda item: str(item.get("nama", "")).lower())
    return matches


def _format_employee_contact_target(employee: dict) -> str:
    return f"{employee['nama']} dari {employee['departemen']}"


def _format_employee_option_label(employee: dict) -> str:
    return f"{employee['nama']} ({employee['departemen']})"


def _resolve_disambiguation_selection(message: str, candidates: list[dict]) -> dict | None:
    stripped = normalize_text_lower(message)
    if not stripped:
        return None

    number_match = re.search(r"\b(\d{1,2})\b", stripped)
    if number_match:
        idx = int(number_match.group(1)) - 1
        if 0 <= idx < len(candidates):
            return candidates[idx]

    for employee in candidates:
        name = normalize_text_lower(str(employee.get("nama", "")))
        department = normalize_text_lower(str(employee.get("departemen", "")))
        if name and department and name in stripped and department in stripped:
            return employee

    for employee in candidates:
        name = normalize_text_lower(str(employee.get("nama", "")))
        department = normalize_text_lower(str(employee.get("departemen", "")))
        if name and name in stripped:
            return employee
        if department and department in stripped:
            return employee

    return None
