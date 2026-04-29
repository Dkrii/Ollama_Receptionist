import logging
import re
from difflib import SequenceMatcher
from typing import Any

from config import settings
from shared.utils.text import normalize_text_lower
from modules.admin.repository import AdminRepository
from modules.chat.constants import PENDING_ACTION_CONTACT_MESSAGE
from modules.chat.utils.slots import (
    extract_department_from_text,
    extract_visitor_goal,
    extract_visitor_name,
    normalize_department,
    normalize_pending_action,
)
from modules.contacts.employees import load_employee_directory
from modules.contacts.service import dispatch_contact_message


_logger = logging.getLogger(__name__)


def _load_employee_directory_safe() -> list[dict]:
    try:
        return load_employee_directory()
    except Exception:
        _logger.exception("chat.employee_directory failed to load")
        return []


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _normalize_department_label(value: str) -> str:
    return normalize_department(value)


def _score_employee_match(employee: dict, query: str) -> float:
    normalized_query = normalize_text_lower(query)
    if not normalized_query:
        return 1.0

    name = normalize_text_lower(str(employee.get("nama", "")))
    department = normalize_text_lower(str(employee.get("departemen", "")))
    position = normalize_text_lower(str(employee.get("jabatan", "")))

    name_score = _similarity(normalized_query, name)
    name_tokens = name.split()
    token_name_score = max([_similarity(normalized_query, token) for token in name_tokens] or [0.0])
    contains_score = 0.75 if normalized_query in name else 0.0
    department_score = _similarity(normalized_query, department) * 0.65
    position_score = _similarity(normalized_query, position) * 0.55

    return max(name_score, token_name_score, contains_score, department_score, position_score)


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

    matches = [employee for employee, _ in filtered_scored]
    if canonical_hint:
        department_matches = [
            employee
            for employee in matches
            if _normalize_department_label(str(employee.get("departemen", ""))) == canonical_hint
        ]
        if department_matches:
            matches = department_matches

    return matches


def _find_department_candidates(department: str) -> list[dict]:
    canonical_department = _normalize_department_label(department)
    if not canonical_department:
        return []

    employees = _load_employee_directory_safe()
    matches: list[dict] = []
    for employee in employees:
        employee_department = _normalize_department_label(str(employee.get("departemen", "")))
        if employee_department == canonical_department:
            matches.append(employee)

    matches.sort(key=lambda item: str(item.get("nama", "")).lower())
    return matches


def _find_employee_by_id(employee_id: int | None) -> dict | None:
    if not employee_id:
        return None
    for employee in _load_employee_directory_safe():
        try:
            if int(employee.get("id")) == int(employee_id):
                return employee
        except Exception:
            continue
    return None


def _format_employee_contact_target(employee: dict) -> str:
    return f"{employee['nama']} dari {employee['departemen']}"


def _format_employee_option_label(employee: dict) -> str:
    return f"{employee['nama']} ({employee['departemen']})"


def _candidate_payload(employee: dict) -> dict[str, Any]:
    return {
        "id": employee.get("id"),
        "nama": employee.get("nama"),
        "departemen": employee.get("departemen"),
        "jabatan": employee.get("jabatan"),
    }


def _resolve_candidate_selection(message: str, candidates: list[dict]) -> dict | None:
    stripped = normalize_text_lower(message)
    if not stripped:
        return None

    number_match = re.search(r"\b(\d{1,2})\b", stripped)
    if number_match:
        index = int(number_match.group(1)) - 1
        if 0 <= index < len(candidates):
            return candidates[index]

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


def _normalize_message_value(value: Any, fallback: str = "-") -> str:
    normalized = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split()).strip()
    return normalized or fallback


def _join_message_blocks(blocks: list[str]) -> str:
    normalized_blocks = [str(block or "").strip() for block in blocks if str(block or "").strip()]
    return "\n\n".join(normalized_blocks)


def _build_contact_message_text(employee: dict[str, Any], visitor_name: str, visitor_goal: str) -> str:
    employee_name = _normalize_message_value(employee.get("nama"), fallback="Bapak/Ibu")
    visitor_name_text = _normalize_message_value(visitor_name)
    visitor_goal_text = _normalize_message_value(visitor_goal)

    blocks = [
        "Notifikasi Virtual Receptionist",
        f"Halo {employee_name}, ada tamu yang ingin menghubungi Anda.",
        f"Nama Tamu: {visitor_name_text}\nKeperluan: {visitor_goal_text}",
        "Mohon tindak lanjut saat Anda tersedia.\nTerima kasih.",
    ]
    return _join_message_blocks(blocks)


def _build_pending_action(
    *,
    selected: dict | None = None,
    target_label: str = "",
    target_kind: str = "person",
    target_department: str = "",
    candidates: list[dict] | None = None,
    confirmed: bool = False,
    visitor_name: str = "",
    visitor_goal: str = "",
) -> dict[str, Any]:
    return {
        "type": PENDING_ACTION_CONTACT_MESSAGE,
        "target_employee_id": int(selected["id"]) if isinstance(selected, dict) and selected.get("id") else None,
        "target_label": target_label or (_format_employee_contact_target(selected) if isinstance(selected, dict) and selected.get("id") else ""),
        "confirmed": bool(confirmed),
        "visitor_name": visitor_name.strip(),
        "visitor_goal": visitor_goal.strip(),
        "target_kind": target_kind,
        "target_department": target_department,
        "candidates": [_candidate_payload(candidate) for candidate in candidates or []],
    }


def _build_disambiguation_prompt(candidates: list[dict], prefix: str) -> str:
    candidate_names = [
        _format_employee_option_label(item)
        for item in candidates
        if isinstance(item, dict) and item.get("nama")
    ]
    if not candidate_names:
        return prefix + " Silakan sebutkan nama lengkap atau divisi yang Anda maksud."
    if len(candidate_names) == 1:
        return prefix + f" Apakah {candidate_names[0]}?"
    if len(candidate_names) == 2:
        listed_names = f"{candidate_names[0]} atau {candidate_names[1]}"
    else:
        listed_names = ", ".join(candidate_names[:-1]) + f", atau {candidate_names[-1]}"
    return prefix + f" Apakah {listed_names}?"


def _default_contact_delivery_detail(status: str) -> str:
    normalized_status = str(status or "").strip().lower()
    if normalized_status == "sent":
        return "Pesan sudah terkirim."
    if normalized_status in {"accepted", "queued"}:
        return "Pesan sudah diterima sistem dan sedang diproses."
    return "Pesan belum berhasil dikirim."


def _build_notify_delivery_answer(employee_name: str, delivery_status: str) -> str:
    normalized_status = str(delivery_status or "").strip().lower()
    if normalized_status == "sent":
        return f"Baik, pesan Anda untuk {employee_name} sudah terkirim. Mohon tunggu beberapa saat."
    if normalized_status in {"accepted", "queued"}:
        return f"Baik, pesan Anda untuk {employee_name} sudah diterima sistem dan sedang diproses. Mohon tunggu beberapa saat."
    return "Maaf, pesan belum bisa terkirim. Silakan coba lagi beberapa saat."


def _dispatch_contact_message(employee: dict, visitor_name: str, visitor_goal: str) -> str:
    initial_message_provider = str(getattr(settings, "contact_messaging_provider", "") or "wablas").strip().lower() or "wablas"
    message_content = _build_contact_message_text(employee, visitor_name, visitor_goal)

    try:
        stored_message = AdminRepository.create_contact_message(
            employee_id=int(employee["id"]),
            employee_nama=str(employee["nama"]),
            employee_departemen=str(employee["departemen"]),
            employee_nomor_wa=str(employee["nomor_wa"]),
            visitor_name=visitor_name,
            visitor_goal=visitor_goal,
            message_text=message_content,
            channel="whatsapp",
            delivery_status="queued",
            delivery_detail="Menunggu dispatcher WhatsApp.",
            delivery_provider=initial_message_provider,
        )
    except Exception:
        _logger.exception("chat.contact message record create failed")
        return "Maaf, pesan belum berhasil diproses. Silakan coba lagi beberapa saat."

    try:
        dispatch_result = dispatch_contact_message(
            employee=employee,
            visitor_name=visitor_name,
            visitor_goal=visitor_goal,
            message_text=message_content,
            message_id=int(stored_message["id"]),
        )
    except Exception as exc:
        _logger.exception("chat.contact message dispatch failed")
        try:
            AdminRepository.update_contact_message_delivery(
                message_id=int(stored_message["id"]),
                delivery_status="failed",
                delivery_detail="Dispatcher WhatsApp gagal dijalankan.",
                delivery_provider=initial_message_provider,
                provider_payload={
                    "error": "dispatch_failed",
                    "detail": str(exc),
                },
                mark_sent=False,
            )
        except Exception:
            _logger.exception("chat.contact message failure update failed")
        return "Maaf, pesan belum berhasil dikirim. Silakan coba lagi beberapa saat."

    try:
        dispatch_status = str(dispatch_result.get("status") or "").strip().lower()
        delivered_payload = AdminRepository.update_contact_message_delivery(
            message_id=int(stored_message["id"]),
            delivery_status=dispatch_status or "failed",
            delivery_detail=str(dispatch_result.get("detail") or _default_contact_delivery_detail(dispatch_status)),
            delivery_provider=str(dispatch_result.get("provider") or initial_message_provider),
            provider_message_id=str(dispatch_result.get("provider_message_id") or ""),
            provider_payload=dispatch_result.get("provider_payload"),
            mark_sent=dispatch_status in {"accepted", "sent"},
        )
    except Exception:
        _logger.exception("chat.contact message delivery update failed")
        dispatch_status = str(dispatch_result.get("status") or "").strip().lower()
        delivered_payload = {
            **(stored_message or {}),
            "delivery_status": dispatch_status or "failed",
        }

    delivery_status = str((delivered_payload or {}).get("delivery_status") or "").strip().lower()
    return _build_notify_delivery_answer(str(employee["nama"]), delivery_status)


def _resolve_target_from_decision(message: str, decision: dict[str, Any]) -> tuple[list[dict], str, str, str]:
    target_type = str(decision.get("target_type") or "none").strip().lower()
    target_value = str(decision.get("target_value") or "").strip()
    target_department = str(decision.get("target_department") or "").strip()

    if target_type == "department" and target_value:
        department = _normalize_department_label(target_value)
        return _find_department_candidates(department), f"tim {department}", "department", department

    search_query = target_value or str(decision.get("search_phrase") or "").strip() or message
    department_hint = target_department or extract_department_from_text(message) or ""
    return _find_employee_candidates(search_query, department_hint=department_hint), search_query, "person", department_hint


def _next_prompt_for_pending(pending_action: dict[str, Any], employee: dict | None) -> tuple[str, dict[str, Any] | None]:
    if not employee:
        candidates = pending_action.get("candidates") if isinstance(pending_action, dict) else []
        if isinstance(candidates, list) and candidates:
            answer = _build_disambiguation_prompt(candidates, "Saya menemukan beberapa nama yang mungkin Anda maksud.")
            return answer, pending_action
        return "Saya belum menemukan karyawan tersebut. Silakan sebutkan nama lengkap atau divisinya.", None

    if not pending_action.get("confirmed"):
        answer = f"Apakah Anda ingin saya sampaikan pesan untuk {_format_employee_contact_target(employee)}?"
        return answer, pending_action

    visitor_name = str(pending_action.get("visitor_name") or "").strip()
    if not visitor_name:
        answer = f"Baik, saya bantu sampaikan pesan untuk {employee['nama']}. Mohon sebutkan nama Anda terlebih dahulu."
        return answer, pending_action

    visitor_goal = str(pending_action.get("visitor_goal") or "").strip()
    if not visitor_goal:
        answer = f"Terima kasih, {visitor_name}. Sekarang mohon sampaikan tujuan atau keperluan Anda."
        return answer, pending_action

    answer = _dispatch_contact_message(employee, visitor_name, visitor_goal)
    return answer, None


def cancel_contact_message(pending_action: dict[str, Any] | None) -> str:
    pending = normalize_pending_action(pending_action)
    if pending and pending.get("target_label"):
        return f"Baik, saya batalkan permintaan untuk menghubungi {pending['target_label']}."
    return "Baik, saya batalkan permintaan kontaknya."


def continue_contact_message(pending_action: dict[str, Any] | None) -> tuple[str, dict[str, Any] | None]:
    pending = normalize_pending_action(pending_action)
    if not pending:
        return "Belum ada proses kontak yang sedang berjalan.", None

    employee = _find_employee_by_id(pending.get("target_employee_id"))
    answer, next_pending = _next_prompt_for_pending(pending, employee)
    return answer, next_pending


def handle_contact_message_turn(
    message: str,
    *,
    pending_action: dict[str, Any] | None,
    decision: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    pending = normalize_pending_action(pending_action)

    if not pending:
        candidates, target_label, target_kind, target_department = _resolve_target_from_decision(message, decision)
        if not candidates:
            return "Saya tidak menemukan karyawan tersebut. Silakan sebutkan nama lengkap atau divisinya.", None

        if len(candidates) > 1:
            answer = _build_disambiguation_prompt(candidates, "Saya menemukan beberapa nama yang mungkin Anda maksud.")
            return answer, _build_pending_action(
                target_label=target_label,
                target_kind=target_kind,
                target_department=target_department,
                candidates=candidates[:5],
            )

        selected = candidates[0]
        visitor_name = str(decision.get("visitor_name") or "").strip()
        visitor_goal = str(decision.get("visitor_goal") or "").strip()
        pending = _build_pending_action(
            selected=selected,
            target_kind=target_kind,
            target_department=target_department,
            confirmed=False,
            visitor_name=visitor_name,
            visitor_goal=visitor_goal,
        )
        answer, next_pending = _next_prompt_for_pending(pending, selected)
        return answer, next_pending

    candidates = pending.get("candidates") if isinstance(pending.get("candidates"), list) else []
    employee = _find_employee_by_id(pending.get("target_employee_id"))
    if not employee and candidates:
        selected = _resolve_candidate_selection(message, candidates)
        if selected:
            employee = selected
            pending = _build_pending_action(
                selected=employee,
                target_kind=str(pending.get("target_kind") or "person"),
                target_department=str(pending.get("target_department") or ""),
                confirmed=False,
                visitor_name=str(pending.get("visitor_name") or ""),
                visitor_goal=str(pending.get("visitor_goal") or ""),
            )

    if not employee:
        candidates_from_decision, target_label, target_kind, target_department = _resolve_target_from_decision(message, decision)
        if candidates_from_decision:
            employee = candidates_from_decision[0] if len(candidates_from_decision) == 1 else None
            if employee:
                pending = _build_pending_action(
                    selected=employee,
                    target_kind=target_kind,
                    target_department=target_department,
                    confirmed=False,
                    visitor_name=str(pending.get("visitor_name") or ""),
                    visitor_goal=str(pending.get("visitor_goal") or ""),
                )
            else:
                answer = _build_disambiguation_prompt(candidates_from_decision, "Saya menemukan beberapa nama yang mungkin Anda maksud.")
                return answer, _build_pending_action(
                    target_label=target_label,
                    target_kind=target_kind,
                    target_department=target_department,
                    candidates=candidates_from_decision[:5],
                    visitor_name=str(pending.get("visitor_name") or ""),
                    visitor_goal=str(pending.get("visitor_goal") or ""),
                )

    if not employee:
        answer, next_pending = _next_prompt_for_pending(pending, None)
        return answer, next_pending

    if decision.get("intent") == "confirm_yes":
        pending["confirmed"] = True
    elif decision.get("intent") == "confirm_no":
        return cancel_contact_message(pending), None

    if not pending.get("visitor_name"):
        visitor_name = str(decision.get("visitor_name") or "").strip()
        if not visitor_name:
            visitor_name = extract_visitor_name(message, selected_name=str(employee.get("nama") or ""))
        if visitor_name:
            pending["visitor_name"] = visitor_name

    if pending.get("visitor_name") and not pending.get("visitor_goal"):
        visitor_goal = str(decision.get("visitor_goal") or "").strip()
        if not visitor_goal and pending.get("confirmed"):
            visitor_goal = extract_visitor_goal(message)
        if visitor_goal:
            pending["visitor_goal"] = visitor_goal

    answer, next_pending = _next_prompt_for_pending(pending, employee)
    return answer, next_pending
