import logging
import re
from difflib import SequenceMatcher
from typing import Any

from api.admin.repository import AdminRepository
from api.chat.intent import (
    detect_conversation_intent,
    extract_department_from_text,
    extract_visitor_goal,
    extract_visitor_name,
    interpret_unavailable_choice,
    message_may_require_contact_intent,
    normalize_department,
)
from api.chat.repository import ChatRepository
from api.chat.utils import normalize_text, store_chat_message
from config import settings
from integrations.contact_dispatch import dispatch_contact_message, normalize_contact_mode, queue_contact_call
from rag.employee_directory import load_employee_directory

_logger = logging.getLogger(__name__)
SYSTEM_CONTACT_TIMEOUT_TOKEN = "__contact_timeout__"

_YES_PATTERNS = (
    r"\bya\b",
    r"\biya\b",
    r"\byes\b",
    r"\bok(?:e)?\b",
    r"\bsetuju\b",
    r"\bbetul\b",
    r"\blanjut\b",
    r"\bboleh\b",
    r"\bsilakan\b",
)
_NO_PATTERNS = (
    r"\btidak\b",
    r"\bnggak\b",
    r"\bga\b",
    r"\bgak\b",
    r"\bno\b",
    r"\bbatal\b",
    r"\bjangan\b",
    r"\btidak jadi\b",
    r"\bga usah\b",
    r"\bnggak usah\b",
)
_LEAVE_MESSAGE_PATTERNS = (
    r"\btinggal(?:kan)? pesan\b",
    r"\btitip pesan\b",
    r"\bpesan saja\b",
    r"\bleave message\b",
)
_WAIT_PATTERNS = (
    r"\btunggu\b",
    r"\bmenunggu\b",
    r"\bwait\b",
    r"\blobby\b",
)


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


def _resolve_chat_memory(conversation_id: str | None, history: list[dict] | None = None) -> tuple[str | None, list[dict], bool]:
    fallback_history = _trim_history(history)
    try:
        resolved_conversation_id = ChatRepository.resolve_conversation(conversation_id)
        prior_history = ChatRepository.get_recent_turns(resolved_conversation_id)
        if not prior_history and not conversation_id:
            prior_history = fallback_history
        return resolved_conversation_id, prior_history, True
    except Exception:
        _logger.exception("chat.memory unavailable conversation_id=%s", conversation_id)
        return None, fallback_history, False


def _list_knowledge_employees() -> list[dict]:
    try:
        return load_employee_directory()
    except Exception:
        _logger.exception("chat.employee_directory failed to load")
        return []


_normalize_text = normalize_text
_store_chat_message = store_chat_message


def _matches_any_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _classify_confirmation_text(message: str) -> str:
    normalized = _normalize_text(message)
    if not normalized:
        return "unknown"

    has_yes = _matches_any_pattern(normalized, _YES_PATTERNS)
    has_no = _matches_any_pattern(normalized, _NO_PATTERNS)

    if has_yes and not has_no:
        return "confirm_yes"
    if has_no and not has_yes:
        return "confirm_no"
    return "unknown"


def _classify_unavailable_choice_fast(message: str) -> str:
    normalized = _normalize_text(message)
    if not normalized:
        return "unknown"

    if _matches_any_pattern(normalized, _LEAVE_MESSAGE_PATTERNS):
        return "leave_message"
    if _matches_any_pattern(normalized, _WAIT_PATTERNS):
        return "wait_in_lobby"

    confirmation = _classify_confirmation_text(normalized)
    if confirmation == "confirm_no":
        return "decline"
    return "unknown"


def _safe_flow_context(flow_state: dict[str, Any] | None) -> dict[str, str]:
    context = flow_state.get("context") if isinstance(flow_state, dict) else {}
    if not isinstance(context, dict):
        context = {}

    return {
        "last_topic_type": str(context.get("last_topic_type") or "none").strip().lower(),
        "last_topic_value": str(context.get("last_topic_value") or "").strip(),
        "last_intent": str(context.get("last_intent") or "unknown").strip().lower(),
    }


def _build_idle_flow_state(context: dict[str, str]) -> dict[str, Any]:
    return {
        "stage": "idle",
        "context": {
            "last_topic_type": str(context.get("last_topic_type") or "none"),
            "last_topic_value": str(context.get("last_topic_value") or ""),
            "last_intent": str(context.get("last_intent") or "unknown"),
        },
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


def _resolve_contact_mode(intent_result: dict[str, Any], flow_state: dict[str, Any] | None = None) -> str:
    intent_mode = normalize_contact_mode(intent_result.get("contact_mode"))
    if intent_mode in {"call", "notify"}:
        return intent_mode

    if isinstance(flow_state, dict):
        saved = str(flow_state.get("action") or "").strip().lower()
        if saved in {"call", "notify"}:
            return saved
    return normalize_contact_mode(None)


def _employee_fuzzy_score(employee: dict, query: str) -> float:
    nq = _normalize_text(query)
    if not nq:
        return 1.0

    nama = _normalize_text(str(employee.get("nama", "")))
    dept = _normalize_text(str(employee.get("departemen", "")))
    jabatan = _normalize_text(str(employee.get("jabatan", "")))

    score_nama = _similarity(nq, nama)
    nama_tokens = nama.split()
    token_scores = [_similarity(nq, t) for t in nama_tokens] if nama_tokens else [0.0]
    score_token_name = max(token_scores)
    score_contains = 0.75 if nq in nama else 0.0
    score_dept = _similarity(nq, dept) * 0.65
    score_jabatan = _similarity(nq, jabatan) * 0.55

    return max(score_nama, score_token_name, score_contains, score_dept, score_jabatan)


def _search_employees(query: str, department_hint: str = "") -> list[dict]:
    employees = _list_knowledge_employees()
    if not query or not _normalize_text(query):
        return employees

    canonical_hint = _normalize_department_label(department_hint)
    scored: list[tuple[dict, float]] = []
    for employee in employees:
        score = _employee_fuzzy_score(employee, query)
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
            _normalize_text(str(item[0].get("nama", ""))),
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


def _search_employees_by_department(department: str) -> list[dict]:
    canonical_dept = _normalize_department_label(department)
    if not canonical_dept:
        return []

    employees = _list_knowledge_employees()
    matches: list[dict] = []
    for employee in employees:
        employee_department = _normalize_department_label(str(employee.get("departemen", "")))
        if employee_department == canonical_dept:
            matches.append(employee)

    matches.sort(key=lambda item: str(item.get("nama", "")).lower())
    return matches


def _format_employee_for_prompt(employee: dict) -> str:
    return f"{employee['nama']} dari {employee['departemen']}"


def _format_employee_name_department(employee: dict) -> str:
    return f"{employee['nama']} ({employee['departemen']})"


def _build_candidate_question(candidates: list[dict], prefix: str) -> str:
    candidate_names = [
        _format_employee_name_department(item)
        for item in candidates
        if isinstance(item, dict) and item.get("nama")
    ]
    if not candidate_names:
        return prefix + " Silakan sebutkan nama lengkap karyawan yang ingin dihubungi."
    if len(candidate_names) == 1:
        return prefix + f" Apakah {candidate_names[0]}?"
    if len(candidate_names) == 2:
        listed_names = f"{candidate_names[0]} atau {candidate_names[1]}"
    else:
        listed_names = ", ".join(candidate_names[:-1]) + f", atau {candidate_names[-1]}"
    return prefix + f" Apakah {listed_names}?"


def _same_contact_target(active_state: dict[str, Any], semantic_intent: dict[str, Any]) -> bool:
    target_type = str(semantic_intent.get("target_type") or "none").strip().lower()
    target_value = _normalize_text(str(semantic_intent.get("target_value") or ""))
    target_department = _normalize_department_label(str(semantic_intent.get("target_department") or ""))

    active_selected = active_state.get("selected") if isinstance(active_state, dict) else {}
    active_target_kind = str((active_state or {}).get("target_kind") or "person").strip().lower()
    active_department = _normalize_department_label(str((active_state or {}).get("department") or ""))
    active_name = _normalize_text(str((active_selected or {}).get("nama") or ""))
    active_selected_department = _normalize_department_label(str((active_selected or {}).get("departemen") or ""))

    if target_type == "department":
        return active_target_kind == "department" and bool(target_department) and active_department == target_department

    if target_type == "person":
        same_name = bool(target_value) and active_name == target_value
        if not target_department:
            return same_name
        return same_name and active_selected_department == target_department

    return False


def _should_restart_contact_flow(
    *,
    stage: str,
    user_message: str,
    safe_flow_state: dict[str, Any],
    semantic_intent: dict[str, Any],
    semantic_contact_usable: bool,
) -> bool:
    if stage not in {
        "await_disambiguation",
        "await_confirmation",
        "contacting_unavailable_pending",
        "await_unavailable_choice",
        "await_waiter_name",
        "await_message_name",
        "await_message_goal",
    }:
        return False

    if not semantic_contact_usable:
        return False

    if _classify_confirmation_text(user_message) != "unknown":
        return False

    if _classify_unavailable_choice_fast(user_message) != "unknown":
        return False

    return not _same_contact_target(safe_flow_state, semantic_intent)


def _build_cancel_contact_answer(selected: dict | None, target_kind: str, department: str) -> str:
    if target_kind == "department" and department:
        return (
            f"Saya sudah membatalkan melanjutkan hubungi ke tim {department}. "
            "Apakah ada yang bisa saya bantu lagi?"
        )

    if isinstance(selected, dict) and selected.get("nama") and selected.get("departemen"):
        return (
            f"Saya sudah membatalkan melanjutkan hubungi ke "
            f"{selected['nama']} ({selected['departemen']}). Apakah ada yang bisa saya bantu lagi?"
        )

    return "Saya sudah membatalkan proses hubungi. Apakah ada yang bisa saya bantu lagi?"


def _build_contact_response(
    *,
    answer: str,
    conversation_id: str | None,
    flow_state: dict[str, Any] | None = None,
    action_result: dict[str, Any] | None = None,
    follow_up: dict[str, Any] | None = None,
) -> dict:
    safe_flow_state = flow_state if isinstance(flow_state, dict) else {"stage": "idle"}
    normalized_answer = " ".join((answer or "").split()).strip()

    payload: dict[str, Any] = {
        "handled": True,
        "answer": normalized_answer,
        "flow_state": safe_flow_state,
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    if action_result:
        payload["action"] = action_result
    if follow_up:
        payload["follow_up"] = follow_up
    return payload


def _resolve_disambiguation_choice(message: str, candidates: list[dict]) -> dict | None:
    stripped = _normalize_text(message)
    if not stripped:
        return None

    number_match = re.search(r"\b(\d{1,2})\b", stripped)
    if number_match:
        idx = int(number_match.group(1)) - 1
        if 0 <= idx < len(candidates):
            return candidates[idx]

    for employee in candidates:
        name = _normalize_text(str(employee.get("nama", "")))
        department = _normalize_text(str(employee.get("departemen", "")))
        if name and department and name in stripped and department in stripped:
            return employee

    for employee in candidates:
        name = _normalize_text(str(employee.get("nama", "")))
        department = _normalize_text(str(employee.get("departemen", "")))
        if name and name in stripped:
            return employee
        if department and department in stripped:
            return employee

    return None


def _perform_contact_action(employee: dict, action: str) -> dict[str, Any]:
    if action == "call":
        dispatch_result = queue_contact_call(employee=employee)
        return {
            "type": "call",
            "status": dispatch_result["status"],
            "provider": dispatch_result["provider"],
            "employee": {
                "id": employee["id"],
                "nama": employee["nama"],
                "departemen": employee["departemen"],
                "jabatan": employee["jabatan"],
            },
            "detail": dispatch_result["detail"],
            "provider_payload": dispatch_result.get("provider_payload"),
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


def _handle_await_disambiguation(ctx: dict) -> dict:
    user_message: str = ctx["message"]
    conversation_id: str | None = ctx["conversation_id"]
    safe_flow_state: dict = ctx["safe_flow_state"]
    flow_context: dict = ctx["flow_context"]
    action: str = ctx["action"]

    def _state(stage: str, **kw: Any) -> dict:
        return _build_stage(stage, flow_context, **kw)

    candidates = safe_flow_state.get("candidates") or []
    if not isinstance(candidates, list) or not candidates:
        answer = "Pilihan kandidat sudah kedaluwarsa. Silakan sebutkan lagi siapa karyawan yang ingin dihubungi."
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_state("idle"))

    selected = _resolve_disambiguation_choice(user_message, candidates)
    if not selected:
        if len(candidates) == 1 and isinstance(candidates[0], dict) and candidates[0].get("id"):
            selected = candidates[0]
            answer = f"Apakah Anda ingin menghubungi {_format_employee_for_prompt(selected)}?"
            _store_chat_message(conversation_id, "assistant", answer)
            return _build_contact_response(
                answer=answer,
                conversation_id=conversation_id,
                flow_state=_state("await_confirmation", action=action, selected=selected),
            )

        answer = _build_candidate_question(candidates, "Saya menemukan beberapa kandidat yang mirip.")
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_state("await_disambiguation", action=action, candidates=candidates),
        )

    answer = f"Apakah Anda ingin menghubungi {_format_employee_for_prompt(selected)}?"
    _store_chat_message(conversation_id, "assistant", answer)
    return _build_contact_response(
        answer=answer,
        conversation_id=conversation_id,
        flow_state=_state("await_confirmation", action=action, selected=selected),
    )


def _handle_await_unavailable_choice(ctx: dict) -> dict:
    user_message: str = ctx["message"]
    conversation_id: str | None = ctx["conversation_id"]
    safe_flow_state: dict = ctx["safe_flow_state"]
    flow_context: dict = ctx["flow_context"]
    action: str = ctx["action"]

    def _state(stage: str, **kw: Any) -> dict:
        return _build_stage(stage, flow_context, **kw)

    selected = safe_flow_state.get("selected") or {}
    target_kind = str(safe_flow_state.get("target_kind") or "person").strip().lower()
    department = _normalize_department_label(str(safe_flow_state.get("department") or ""))

    if not isinstance(selected, dict) or not selected.get("id"):
        answer = "Sesi tidak tersedia berakhir. Silakan ulangi permintaan hubungi karyawan."
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_state("idle"))

    choice_decision = _classify_unavailable_choice_fast(user_message)
    if choice_decision == "unknown":
        choice_result = interpret_unavailable_choice(user_message, safe_flow_state)
        choice_decision = str(choice_result.get("decision") or "unknown").strip().lower()

    if choice_decision == "leave_message":
        answer = "Baik, saya bantu tinggalkan pesan. Mohon sebutkan nama Anda terlebih dahulu."
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_state("await_message_name", action=action, selected=selected, target_kind=target_kind, department=department),
        )

    if choice_decision == "decline":
        answer = "Baik, Anda tidak meninggalkan pesan. Silakan menuju front office untuk bantuan lebih lanjut secara offline."
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_state("idle"))

    if choice_decision == "wait_in_lobby":
        answer = (
            f"Baik, silakan sebutkan nama Anda. "
            f"Saya akan menyampaikan kepada {selected['nama']} bahwa Anda menunggu di lobby."
        )
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_state("await_waiter_name", action=action, selected=selected, target_kind=target_kind, department=department),
        )

    if target_kind == "department" and department:
        answer = (
            f"Saat ini tim {department} sedang tidak tersedia. "
            "Anda bisa memilih meninggalkan pesan atau menunggu di lobby. Apa yang ingin Anda lakukan?"
        )
    else:
        answer = (
            f"{selected['nama']} sedang tidak tersedia saat ini. "
            "Anda bisa memilih meninggalkan pesan atau menunggu di lobby. Apa yang ingin Anda lakukan?"
        )
    _store_chat_message(conversation_id, "assistant", answer)
    return _build_contact_response(
        answer=answer,
        conversation_id=conversation_id,
        flow_state=_state("await_unavailable_choice", action=action, selected=selected, target_kind=target_kind, department=department),
    )


def _handle_contacting_unavailable_pending(ctx: dict) -> dict:
    user_message: str = ctx["message"]
    conversation_id: str | None = ctx["conversation_id"]
    safe_flow_state: dict = ctx["safe_flow_state"]
    flow_context: dict = ctx["flow_context"]
    action: str = ctx["action"]

    def _state(stage: str, **kw: Any) -> dict:
        return _build_stage(stage, flow_context, **kw)

    selected = safe_flow_state.get("selected") or {}
    target_kind = str(safe_flow_state.get("target_kind") or "person").strip().lower()
    department = _normalize_department_label(str(safe_flow_state.get("department") or ""))

    if not isinstance(selected, dict) or not selected.get("id"):
        answer = "Sesi panggilan berakhir. Silakan ulangi permintaan hubungi karyawan."
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_state("idle"))

    if _normalize_text(user_message) == SYSTEM_CONTACT_TIMEOUT_TOKEN:
        if target_kind == "department" and department:
            answer = f"Saat ini tim {department} sedang tidak tersedia. Apakah Anda ingin meninggalkan pesan?"
        else:
            answer = (
                f"{selected['nama']} sedang tidak tersedia saat ini. "
                f"Anda bisa tinggalkan pesan untuk {selected['nama']} "
                "Apakah anda ingin meninggalkan pesan?"
            )
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_state("await_unavailable_choice", action=action, selected=selected, target_kind=target_kind, department=department),
        )

    return _handle_await_unavailable_choice(ctx)


def _handle_await_confirmation(ctx: dict) -> dict:
    user_message: str = ctx["message"]
    conversation_id: str | None = ctx["conversation_id"]
    safe_flow_state: dict = ctx["safe_flow_state"]
    flow_context: dict = ctx["flow_context"]
    action: str = ctx["action"]

    def _state(stage: str, **kw: Any) -> dict:
        return _build_stage(stage, flow_context, **kw)

    selected = safe_flow_state.get("selected") or {}
    target_kind = str(safe_flow_state.get("target_kind") or "person").strip().lower()
    department = _normalize_department_label(str(safe_flow_state.get("department") or ""))
    candidates = safe_flow_state.get("candidates") or []

    if target_kind == "department" and (not isinstance(selected, dict) or not selected.get("id")):
        if isinstance(candidates, list) and candidates:
            selected = candidates[0]
        elif department:
            dept_matches = _search_employees_by_department(department)
            selected = dept_matches[0] if dept_matches else {}

    if not isinstance(selected, dict) or not selected.get("id"):
        answer = "Sesi konfirmasi sudah berakhir. Silakan ulangi permintaan hubungi karyawan."
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_state("idle"))

    current_intent = _classify_confirmation_text(user_message)
    if current_intent == "confirm_no":
        if target_kind == "person" and isinstance(candidates, list) and len(candidates) > 1:
            remaining_candidates = [
                item for item in candidates
                if str(item.get("id") or "") != str(selected.get("id") or "")
            ]
            if remaining_candidates:
                if len(remaining_candidates) == 1 and isinstance(remaining_candidates[0], dict) and remaining_candidates[0].get("id"):
                    fallback_selected = remaining_candidates[0]
                    answer = f"Baik, bagaimana jika {_format_employee_for_prompt(fallback_selected)}?"
                    _store_chat_message(conversation_id, "assistant", answer)
                    return _build_contact_response(
                        answer=answer,
                        conversation_id=conversation_id,
                        flow_state=_state(
                            "await_confirmation",
                            action=action,
                            selected=fallback_selected,
                            target_kind="person",
                            candidates=remaining_candidates,
                        ),
                    )

                answer = _build_candidate_question(remaining_candidates, "Baik, saya carikan kandidat lain yang paling mirip.")

                _store_chat_message(conversation_id, "assistant", answer)
                return _build_contact_response(
                    answer=answer,
                    conversation_id=conversation_id,
                    flow_state=_state("await_disambiguation", action=action, candidates=remaining_candidates),
                )

        answer = _build_cancel_contact_answer(selected, target_kind, department)
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_state("idle"))

    if current_intent != "confirm_yes":
        answer = (
            "Silakan jawab terlebih dahulu, apakah Anda ingin melanjutkan hubungi "
            f"{selected['nama']} ({selected['departemen']})?"
        )
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_state("await_confirmation", action=action, selected=selected, target_kind=target_kind, department=department, candidates=candidates),
        )

    try:
        action_result = _perform_contact_action(selected, action)
    except Exception:
        _logger.exception("chat.contact action dispatch failed")
        answer = "Maaf, sistem belum berhasil memproses permintaan hubungi saat ini."
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_state("idle"))

    if target_kind == "department" and department:
        answer = f"Baik, saya akan menghubungkan Anda dengan staf {department} yang tersedia. Sedang diproses, mohon tunggu 5-10 detik."
    else:
        answer = f"Baik, saya sedang menghubungi {selected['nama']}. Silakan tunggu 5-10 detik."

    _store_chat_message(conversation_id, "assistant", answer)
    return _build_contact_response(
        answer=answer,
        conversation_id=conversation_id,
        flow_state=_state("contacting_unavailable_pending", action=action, selected=selected, target_kind=target_kind, department=department),
        action_result=action_result,
        follow_up={
            "mode": "countdown-check",
            "duration_seconds": 10,
            "countdown": {"start": 10, "end": 0, "show_icon": True},
            "pre_countdown_answer": "Mohon tunggu 10 detik, saya cek ketersediaannya dulu.",
            "message": SYSTEM_CONTACT_TIMEOUT_TOKEN,
        },
    )


def _handle_await_waiter_name(ctx: dict) -> dict:
    user_message: str = ctx["message"]
    conversation_id: str | None = ctx["conversation_id"]
    safe_flow_state: dict = ctx["safe_flow_state"]
    flow_context: dict = ctx["flow_context"]
    action: str = ctx["action"]

    def _state(stage: str, **kw: Any) -> dict:
        return _build_stage(stage, flow_context, **kw)

    selected = safe_flow_state.get("selected") or {}
    target_kind = str(safe_flow_state.get("target_kind") or "person").strip().lower()
    department = _normalize_department_label(str(safe_flow_state.get("department") or ""))

    if not isinstance(selected, dict) or not selected.get("id"):
        answer = "Sesi menunggu berakhir. Silakan ulangi permintaan hubungi karyawan."
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_state("idle"))

    visitor_name = extract_visitor_name(user_message, safe_flow_state)
    if not visitor_name:
        answer = "Silakan sebutkan nama Anda terlebih dahulu."
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_state("await_waiter_name", action=action, selected=selected, target_kind=target_kind, department=department),
        )

    answer = f"Baik, {visitor_name}. Saya akan menyampaikan kepada {selected['nama']} bahwa Anda menunggu di lobby."
    _store_chat_message(conversation_id, "assistant", answer)
    return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_state("idle"))


def _handle_await_message_name(ctx: dict) -> dict:
    user_message: str = ctx["message"]
    conversation_id: str | None = ctx["conversation_id"]
    safe_flow_state: dict = ctx["safe_flow_state"]
    flow_context: dict = ctx["flow_context"]
    action: str = ctx["action"]

    def _state(stage: str, **kw: Any) -> dict:
        return _build_stage(stage, flow_context, **kw)

    selected = safe_flow_state.get("selected") or {}
    target_kind = str(safe_flow_state.get("target_kind") or "person").strip().lower()
    department = _normalize_department_label(str(safe_flow_state.get("department") or ""))

    if not isinstance(selected, dict) or not selected.get("id"):
        answer = "Sesi pesan berakhir. Silakan ulangi permintaan hubungi karyawan."
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_state("idle"))

    visitor_name = extract_visitor_name(user_message, safe_flow_state)
    if not visitor_name:
        answer = "Mohon sebutkan nama Anda terlebih dahulu agar saya bisa mencatat pesannya."
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_state("await_message_name", action=action, selected=selected, target_kind=target_kind, department=department),
        )

    answer = f"Terima kasih, {visitor_name}. Sekarang mohon sampaikan tujuan atau keperluan Anda."
    _store_chat_message(conversation_id, "assistant", answer)
    return _build_contact_response(
        answer=answer,
        conversation_id=conversation_id,
        flow_state=_state("await_message_goal", action=action, selected=selected, target_kind=target_kind, department=department, visitor_name=visitor_name),
    )


def _handle_await_message_goal(ctx: dict) -> dict:
    user_message: str = ctx["message"]
    conversation_id: str | None = ctx["conversation_id"]
    safe_flow_state: dict = ctx["safe_flow_state"]
    flow_context: dict = ctx["flow_context"]
    action: str = ctx["action"]

    def _state(stage: str, **kw: Any) -> dict:
        return _build_stage(stage, flow_context, **kw)

    selected = safe_flow_state.get("selected") or {}
    target_kind = str(safe_flow_state.get("target_kind") or "person").strip().lower()
    department = _normalize_department_label(str(safe_flow_state.get("department") or ""))
    visitor_name = str(safe_flow_state.get("visitor_name") or "").strip()

    if not isinstance(selected, dict) or not selected.get("id"):
        answer = "Sesi pesan berakhir. Silakan ulangi permintaan hubungi karyawan."
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_state("idle"))

    if not visitor_name:
        answer = "Mohon sebutkan nama Anda terlebih dahulu sebelum menyampaikan tujuan."
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_state("await_message_name", action=action, selected=selected, target_kind=target_kind, department=department),
        )

    visitor_goal = extract_visitor_goal(user_message, safe_flow_state)
    if len(visitor_goal) < 5:
        answer = "Tujuannya masih terlalu singkat. Mohon jelaskan tujuan Anda dengan lebih lengkap."
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_state("await_message_goal", action=action, selected=selected, target_kind=target_kind, department=department, visitor_name=visitor_name),
        )

    stored_message: dict[str, Any] | None = None
    try:
        message_content = f"Nama: {visitor_name}; Tujuan: {visitor_goal}"
        stored_message = AdminRepository.create_contact_message(
            employee_id=int(selected["id"]),
            employee_nama=str(selected["nama"]),
            employee_departemen=str(selected["departemen"]),
            employee_nomor_wa=str(selected["nomor_wa"]),
            visitor_name=visitor_name,
            visitor_goal=visitor_goal,
            message_text=message_content,
            channel="whatsapp",
            delivery_status="queued",
            delivery_detail="Menunggu dispatcher WhatsApp.",
            delivery_provider=str(getattr(settings, "contact_message_delivery_mode", "dummy") or "dummy"),
        )
        dispatch_result = dispatch_contact_message(
            employee=selected,
            visitor_name=visitor_name,
            visitor_goal=visitor_goal,
            message_text=message_content,
        )
        delivered_payload = AdminRepository.update_contact_message_delivery(
            message_id=int(stored_message["id"]),
            delivery_status=str(dispatch_result.get("status") or "sent"),
            delivery_detail=str(dispatch_result.get("detail") or "Pesan berhasil diteruskan."),
            delivery_provider=str(dispatch_result.get("provider") or "dummy"),
            provider_message_id=str(dispatch_result.get("provider_message_id") or ""),
            provider_payload=dispatch_result.get("provider_payload"),
            mark_sent=str(dispatch_result.get("status") or "").strip().lower() in {"sent", "sent_dummy"},
        )
    except Exception:
        _logger.exception("chat.contact message dispatch failed")
        if stored_message and stored_message.get("id"):
            try:
                AdminRepository.update_contact_message_delivery(
                    message_id=int(stored_message["id"]),
                    delivery_status="failed",
                    delivery_detail="Dispatcher WhatsApp gagal dijalankan.",
                    delivery_provider=str(getattr(settings, "contact_message_delivery_mode", "dummy") or "dummy"),
                    provider_payload={"error": "dispatch_failed"},
                    mark_sent=False,
                )
            except Exception:
                _logger.exception("chat.contact message failure update failed")
        answer = "Maaf, pesan belum berhasil dikirim. Silakan menuju front office untuk bantuan offline."
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_state("idle"))

    delivery_status = str((delivered_payload or {}).get("delivery_status") or "").strip().lower()
    if delivery_status in {"queued", "queued_dummy"}:
        answer = (
            f"Baik, pesan Anda untuk {selected['nama']} sudah dicatat dan sedang diproses. "
            "Silakan menuju lobby sambil menunggu, atau ke front office jika butuh bantuan offline."
        )
    else:
        answer = (
            f"Baik, pesan Anda untuk {selected['nama']} sudah terkirim. "
            "Silakan menuju lobby sambil menunggu, atau ke front office jika butuh bantuan offline."
        )
    _store_chat_message(conversation_id, "assistant", answer)
    return _build_contact_response(
        answer=answer,
        conversation_id=conversation_id,
        flow_state=_state("idle"),
        action_result={
            "type": "notify",
            "status": str((delivered_payload or {}).get("delivery_status") or "sent"),
            "provider": str((delivered_payload or {}).get("delivery_provider") or "dummy"),
            "employee": {
                "id": selected["id"],
                "nama": selected["nama"],
                "departemen": selected["departemen"],
                "jabatan": selected["jabatan"],
            },
            "message": delivered_payload,
        },
    )


def _handle_new_contact_intent(ctx: dict) -> dict:
    user_message: str = ctx["message"]
    conversation_id: str | None = ctx["conversation_id"]
    flow_context: dict = ctx["flow_context"]
    action: str = ctx["action"]
    semantic_intent: dict = ctx["semantic_intent"]

    def _state(stage: str, **kw: Any) -> dict:
        return _build_stage(stage, flow_context, **kw)

    semantic_target_type = str(semantic_intent.get("target_type") or "none").strip().lower()
    semantic_target_value = str(semantic_intent.get("target_value") or "").strip()
    department_target = ""

    if semantic_target_type == "department" and semantic_target_value:
        department_target = _normalize_department_label(semantic_target_value)

    if department_target:
        dept_matches = _search_employees_by_department(department_target)
        if not dept_matches:
            answer = f"Saat ini saya belum menemukan staf terdaftar di tim {department_target}."
            _store_chat_message(conversation_id, "assistant", answer)
            return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_state("idle"))

        selected = dept_matches[0]
        answer = f"Tentu, apakah Anda ingin saya menghubungkan Anda dengan tim {department_target}?"
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_state("await_confirmation", action=action, target_kind="department", department=department_target, selected=selected, candidates=dept_matches[:5]),
        )

    if semantic_target_type == "person" and semantic_target_value:
        search_query = semantic_target_value
    else:
        search_query = str(semantic_intent.get("search_phrase") or "").strip() or user_message
    department_hint = (
        str(semantic_intent.get("target_department") or "").strip()
        or extract_department_from_text(user_message)
        or ""
    )
    matches = _search_employees(search_query, department_hint=department_hint)

    if not matches:
        answer = "Saya tidak menemukan karyawan tersebut. Silakan sebutkan nama lengkap atau divisinya."
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_state("idle"))

    if len(matches) == 1:
        selected = matches[0]
        answer = f"Apakah Anda ingin menghubungi {_format_employee_for_prompt(selected)}?"
        _store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_state("await_confirmation", action=action, selected=selected, target_kind="person"),
        )

    candidates = matches
    answer = _build_candidate_question(candidates, "Saya menemukan beberapa kandidat yang mirip.")
    _store_chat_message(conversation_id, "assistant", answer)
    return _build_contact_response(
        answer=answer,
        conversation_id=conversation_id,
        flow_state=_state("await_disambiguation", action=action, candidates=candidates),
    )


_STAGE_HANDLERS: dict[str, Any] = {
    "await_disambiguation": _handle_await_disambiguation,
    "await_confirmation": _handle_await_confirmation,
    "contacting_unavailable_pending": _handle_contacting_unavailable_pending,
    "await_unavailable_choice": _handle_await_unavailable_choice,
    "await_waiter_name": _handle_await_waiter_name,
    "await_message_name": _handle_await_message_name,
    "await_message_goal": _handle_await_message_goal,
}


def _default_semantic_intent() -> dict[str, Any]:
    return {
        "intent": "unknown",
        "confidence": 0.0,
        "target_type": "none",
        "target_value": "",
        "target_department": "",
        "action": "none",
        "contact_mode": "auto",
        "search_phrase": "",
    }


def _should_probe_contact_intent(
    *,
    user_message: str,
    stage: str,
    is_active_stage: bool,
    safe_flow_state: dict[str, Any],
) -> bool:
    if not user_message:
        return False

    is_internal_timeout_event = (
        stage == "contacting_unavailable_pending"
        and _normalize_text(user_message) == SYSTEM_CONTACT_TIMEOUT_TOKEN
    )
    if is_internal_timeout_event:
        return False

    if not message_may_require_contact_intent(user_message, safe_flow_state):
        return False

    if not is_active_stage:
        return True

    active_stage_allows_new_target = (
        _classify_confirmation_text(user_message) == "unknown"
        and _classify_unavailable_choice_fast(user_message) == "unknown"
    )
    return active_stage_allows_new_target


def _resolve_semantic_contact_usable(user_message: str, semantic_intent: dict[str, Any]) -> bool:
    semantic_target_type = str(semantic_intent.get("target_type") or "none").strip().lower()
    semantic_target_value = str(semantic_intent.get("target_value") or "").strip()
    semantic_action = str(semantic_intent.get("action") or "none").strip().lower()
    semantic_contact_detected = (
        str(semantic_intent.get("intent") or "").strip().lower() == "contact_employee"
    )

    if not (semantic_contact_detected and semantic_action == "contact"):
        return False

    semantic_contact_has_explicit_target = (
        semantic_target_type in {"person", "department"}
        and bool(semantic_target_value)
    )
    if semantic_contact_has_explicit_target:
        return True

    fallback_query = str(semantic_intent.get("search_phrase") or "").strip() or user_message
    fallback_matches = _search_employees(
        fallback_query,
        department_hint=str(semantic_intent.get("target_department") or "").strip() or extract_department_from_text(user_message) or "",
    )
    return bool(fallback_matches)


def handle_contact_flow(
    message: str,
    conversation_id: str | None = None,
    history: list[dict] | None = None,
    flow_state: dict[str, Any] | None = None,
) -> dict:
    resolved_conversation_id, prior_history, _ = _resolve_chat_memory(conversation_id, history=history)
    user_message = (message or "").strip()
    safe_flow_state = flow_state if isinstance(flow_state, dict) else {}
    stage = str(safe_flow_state.get("stage") or "idle").strip().lower()
    is_active_stage = stage in _STAGE_HANDLERS
    base_context = _safe_flow_context(safe_flow_state)
    is_internal_timeout_event = (
        stage == "contacting_unavailable_pending"
        and _normalize_text(user_message) == SYSTEM_CONTACT_TIMEOUT_TOKEN
    )
    should_probe_intent_llm = _should_probe_contact_intent(
        user_message=user_message,
        stage=stage,
        is_active_stage=is_active_stage,
        safe_flow_state=safe_flow_state,
    )
    semantic_intent = (
        detect_conversation_intent(
            user_message,
            flow_state=safe_flow_state,
            allow_llm=True,
        )
        if should_probe_intent_llm
        else _default_semantic_intent()
    )
    action = _resolve_contact_mode(semantic_intent, safe_flow_state)
    flow_context = _update_flow_context_from_intent(base_context, semantic_intent)

    if not user_message:
        return {
            "handled": False,
            "flow_state": _build_idle_flow_state(flow_context),
            "conversation_id": resolved_conversation_id,
            "history": prior_history,
        }

    semantic_contact_usable = _resolve_semantic_contact_usable(user_message, semantic_intent)

    if _should_restart_contact_flow(
        stage=stage,
        user_message=user_message,
        safe_flow_state=safe_flow_state,
        semantic_intent=semantic_intent,
        semantic_contact_usable=semantic_contact_usable,
    ):
        safe_flow_state = {}
        stage = "idle"
        is_active_stage = False

    if not is_active_stage and not semantic_contact_usable:
        return {
            "handled": False,
            "flow_state": _build_idle_flow_state(flow_context),
            "conversation_id": resolved_conversation_id,
            "history": prior_history,
        }

    if not is_internal_timeout_event:
        _store_chat_message(resolved_conversation_id, "user", user_message)

    ctx: dict[str, Any] = {
        "message": user_message,
        "conversation_id": resolved_conversation_id,
        "safe_flow_state": safe_flow_state,
        "flow_context": flow_context,
        "action": action,
        "semantic_intent": semantic_intent,
    }
    handler = _STAGE_HANDLERS.get(stage)
    if handler:
        return handler(ctx)
    return _handle_new_contact_intent(ctx)
