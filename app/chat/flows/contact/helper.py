import logging
import re
from difflib import SequenceMatcher
from typing import Any

from chat.memory import normalize_text
from chat.nlu import normalize_department
from config import settings
from contacts.call.api_service import ContactCallService
from contacts.employees import load_employee_directory
from storage.chat_repository import ChatRepository


_logger = logging.getLogger(__name__)


def _trim_history(history: list[dict] | None) -> list[dict]:
    if not history:
        return []

    trimmed_history: list[dict] = []
    for item in history[-settings.chat_recent_turns:]:
        role = str(item.get("role", "")).strip()
        content = str(item.get("content", "")).strip()
        if not role or not content:
            continue
        trimmed_history.append({"role": role, "content": content})
    return trimmed_history

def _resolve_chat_memory(
    conversation_id: str | None,
    history: list[dict] | None = None,
) -> tuple[str | None, list[dict]]:
    fallback_history = _trim_history(history)
    try:
        resolved_conversation_id = ChatRepository.resolve_conversation(conversation_id)
        prior_history = ChatRepository.get_recent_turns(resolved_conversation_id)
        if not prior_history and not conversation_id:
            prior_history = fallback_history
        return resolved_conversation_id, prior_history
    except Exception:
        _logger.exception("chat.memory unavailable conversation_id=%s", conversation_id)
        return None, fallback_history

def _load_employee_directory_safe() -> list[dict]:
    try:
        return load_employee_directory()
    except Exception:
        _logger.exception("chat.employee_directory failed to load")
        return []

def _extract_flow_context(flow_state: dict[str, Any] | None) -> dict[str, str]:
    context = flow_state.get("context") if isinstance(flow_state, dict) else {}
    if not isinstance(context, dict):
        context = {}

    return {
        "last_topic_type": str(context.get("last_topic_type") or "none").strip().lower(),
        "last_topic_value": str(context.get("last_topic_value") or "").strip(),
        "last_intent": str(context.get("last_intent") or "unknown").strip().lower(),
    }

def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()

def _normalize_department_label(value: str) -> str:
    return normalize_department(value)

def _update_flow_context_from_intent(
    base_context: dict[str, str],
    intent_result: dict[str, Any],
) -> dict[str, str]:
    context = {
        "last_topic_type": str(base_context.get("last_topic_type") or "none"),
        "last_topic_value": str(base_context.get("last_topic_value") or ""),
        "last_intent": str(base_context.get("last_intent") or "unknown"),
    }

    intent = str(intent_result.get("intent") or "unknown").strip().lower()
    target_type = str(intent_result.get("target_type") or "none").strip().lower()
    target_value = str(intent_result.get("target_value") or "").strip()

    if intent in {"company_info", "contact_employee"} and target_type in {"department", "person"} and target_value:
        context["last_topic_type"] = target_type
        context["last_topic_value"] = _normalize_department_label(target_value) if target_type == "department" else target_value

    context["last_intent"] = intent
    return context

def _score_employee_match(employee: dict, query: str) -> float:
    nq = normalize_text(query)
    if not nq:
        return 1.0

    nama = normalize_text(str(employee.get("nama", "")))
    dept = normalize_text(str(employee.get("departemen", "")))
    jabatan = normalize_text(str(employee.get("jabatan", "")))

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
    if not query or not normalize_text(query):
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
            normalize_text(str(item[0].get("nama", ""))),
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
    stripped = normalize_text(message)
    if not stripped:
        return None

    number_match = re.search(r"\b(\d{1,2})\b", stripped)
    if number_match:
        idx = int(number_match.group(1)) - 1
        if 0 <= idx < len(candidates):
            return candidates[idx]

    for employee in candidates:
        name = normalize_text(str(employee.get("nama", "")))
        department = normalize_text(str(employee.get("departemen", "")))
        if name and department and name in stripped and department in stripped:
            return employee

    for employee in candidates:
        name = normalize_text(str(employee.get("nama", "")))
        department = normalize_text(str(employee.get("departemen", "")))
        if name and name in stripped:
            return employee
        if department and department in stripped:
            return employee

    return None

def _start_contact_request(employee: dict, action: str) -> dict[str, Any]:
    if action == "call":
        stored_call = ContactCallService.create_session_for_employee(employee)
        return {
            "type": "start_two_way_call",
            "status": str((stored_call or {}).get("call_status") or "preparing"),
            "provider": str((stored_call or {}).get("call_provider") or "twilio"),
            "employee": {
                "id": employee["id"],
                "nama": employee["nama"],
                "departemen": employee["departemen"],
                "jabatan": employee["jabatan"],
                "nomor_wa": employee["nomor_wa"],
            },
            "detail": str((stored_call or {}).get("call_detail") or ""),
            "call_session_id": str((stored_call or {}).get("call_session_id") or ""),
            "dev_identity": str((stored_call or {}).get("dev_identity") or ""),
            "provider_payload": (stored_call or {}).get("provider_payload"),
            "call": stored_call,
        }

    return {
        "type": "notify",
        "status": "queued",
        "provider": "workflow",
        "employee": {
            "id": employee["id"],
            "nama": employee["nama"],
            "departemen": employee["departemen"],
            "jabatan": employee["jabatan"],
            "nomor_wa": employee["nomor_wa"],
        },
        "detail": "Permintaan kontak diterima dan sistem sedang mengecek ketersediaan karyawan.",
    }

def _build_stage(stage: str, flow_context: dict, **kwargs: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"stage": stage, "context": flow_context}
    result.update(kwargs)
    return result

def _build_contact_message_text(employee: dict[str, Any], visitor_name: str, visitor_goal: str) -> str:
    employee_name = str(employee.get("nama") or "Bapak/Ibu").strip() or "Bapak/Ibu"

    lines = [
        "Notifikasi Virtual Receptionist",
        f"Halo {employee_name}, ada tamu yang ingin menghubungi Anda.",
        f"Nama Tamu: {visitor_name}",
        f"Keperluan: {visitor_goal}",
        "Mohon tindak lanjut saat Anda tersedia.",
        "Terima kasih.",
    ]
    return "\n".join(lines)

def _unpack_ctx(ctx: dict) -> tuple:
    """Unpack semua field ctx yang dipakai oleh setiap stage handler."""
    return (
        ctx["message"],
        ctx["conversation_id"],
        ctx["safe_flow_state"],
        ctx["flow_context"],
        ctx["action"],
    )

def _extract_session(safe_flow_state: dict) -> tuple[dict, str, str]:
    """Ekstrak selected, target_kind, department dari flow state."""
    selected = safe_flow_state.get("selected") or {}
    target_kind = str(safe_flow_state.get("target_kind") or "person").strip().lower()
    department = _normalize_department_label(str(safe_flow_state.get("department") or ""))
    return selected, target_kind, department
