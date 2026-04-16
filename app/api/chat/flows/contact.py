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
from lib.contact import (
    dispatch_contact_message,
    normalize_contact_mode,
    queue_contact_call,
)
from rag.employee_directory import load_employee_directory

_logger = logging.getLogger(__name__)

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
_EXPLICIT_NOTIFY_PATTERNS = _LEAVE_MESSAGE_PATTERNS + (
    r"\bwhatsapp\b",
    r"\bwa\b",
    r"\bkirim(?:kan)? pesan\b",
    r"\bchat\b",
)


# ============================================================================
# LANGKAH 1: RESOLVE CONVERSATION DAN FLOW CONTEXT
# ============================================================================


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


def _matches_any_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _classify_confirmation_reply(message: str) -> str:
    normalized = normalize_text(message)
    if not normalized:
        return "unknown"

    has_yes = _matches_any_pattern(normalized, _YES_PATTERNS)
    has_no = _matches_any_pattern(normalized, _NO_PATTERNS)

    if has_yes and not has_no:
        return "confirm_yes"
    if has_no and not has_yes:
        return "confirm_no"
    return "unknown"


def _classify_unavailable_choice_rule_based(message: str) -> str:
    normalized = normalize_text(message)
    if not normalized:
        return "unknown"

    if _matches_any_pattern(normalized, _LEAVE_MESSAGE_PATTERNS):
        return "leave_message"
    if _matches_any_pattern(normalized, _WAIT_PATTERNS):
        return "wait_in_lobby"

    confirmation = _classify_confirmation_reply(normalized)
    if confirmation == "confirm_no":
        return "decline"
    return "unknown"


def _extract_flow_context(flow_state: dict[str, Any] | None) -> dict[str, str]:
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


# ============================================================================
# LANGKAH 2: DETEKSI INTENT CONTACT DAN PRE-FILTER FLOW
# ============================================================================


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


def _is_explicit_notify_request(message: str) -> bool:
    normalized = normalize_text(message)
    if not normalized:
        return False
    return any(re.search(pattern, normalized) for pattern in _EXPLICIT_NOTIFY_PATTERNS)


def _resolve_contact_mode(
    intent_result: dict[str, Any],
    flow_state: dict[str, Any] | None = None,
    user_message: str = "",
) -> str:
    intent_mode = normalize_contact_mode(intent_result.get("contact_mode"))
    if intent_mode == "call":
        return "call"
    if intent_mode == "notify" and _is_explicit_notify_request(user_message):
        return "notify"

    if isinstance(flow_state, dict):
        saved = str(flow_state.get("action") or "").strip().lower()
        if saved in {"call", "notify"}:
            return saved
    return "call"


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


def _build_disambiguation_prompt(candidates: list[dict], prefix: str) -> str:
    candidate_names = [
        _format_employee_option_label(item)
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


def _is_same_contact_target(active_flow_state: dict[str, Any], semantic_intent: dict[str, Any]) -> bool:
    target_type = str(semantic_intent.get("target_type") or "none").strip().lower()
    target_value = normalize_text(str(semantic_intent.get("target_value") or ""))
    target_department = _normalize_department_label(str(semantic_intent.get("target_department") or ""))

    active_selected = active_flow_state.get("selected") if isinstance(active_flow_state, dict) else {}
    active_target_kind = str((active_flow_state or {}).get("target_kind") or "person").strip().lower()
    active_department = _normalize_department_label(str((active_flow_state or {}).get("department") or ""))
    active_name = normalize_text(str((active_selected or {}).get("nama") or ""))
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
    active_flow_state: dict[str, Any],
    semantic_intent: dict[str, Any],
    semantic_contact_usable: bool,
) -> bool:
    if stage not in {
        "await_disambiguation",
        "await_confirmation",
        "await_unavailable_choice",
        "await_waiter_name",
        "await_message_name",
        "await_message_goal",
    }:
        return False

    if not semantic_contact_usable:
        return False

    if _classify_confirmation_reply(user_message) != "unknown":
        return False

    if _classify_unavailable_choice_rule_based(user_message) != "unknown":
        return False

    return not _is_same_contact_target(active_flow_state, semantic_intent)


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


def _build_unavailable_contact_answer(selected: dict, target_kind: str, department: str) -> str:
    if target_kind == "department" and department:
        return (
            f"Saya sudah mencoba menghubungi tim {department}, tetapi belum ada respons. "
            "Anda bisa memilih meninggalkan pesan atau menunggu di lobby. Apa yang ingin Anda lakukan?"
        )

    return (
        f"Saya sudah mencoba menghubungi {selected['nama']}, tetapi belum ada respons. "
        "Anda bisa memilih meninggalkan pesan atau menunggu di lobby. Apa yang ingin Anda lakukan?"
    )


def _build_follow_up_choices(stage: str, options: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "type": "choices",
        "stage": stage,
        "options": options,
    }


def _build_confirmation_follow_up() -> dict[str, Any]:
    return _build_follow_up_choices(
        "await_confirmation",
        [
            {"id": "confirm_yes", "label": "Ya, lanjutkan", "value": "ya"},
            {"id": "confirm_no", "label": "Tidak", "value": "tidak"},
        ],
    )


def _build_disambiguation_follow_up(candidates: list[dict]) -> dict[str, Any]:
    options: list[dict[str, str]] = []
    for index, candidate in enumerate(candidates[:5], start=1):
        if not isinstance(candidate, dict) or not candidate.get("nama"):
            continue
        options.append(
            {
                "id": f"candidate_{candidate.get('id') or index}",
                "label": _format_employee_option_label(candidate),
                "value": str(index),
            }
        )
    return _build_follow_up_choices("await_disambiguation", options)


def _build_unavailable_follow_up() -> dict[str, Any]:
    return _build_follow_up_choices(
        "await_unavailable_choice",
        [
            {"id": "leave_message", "label": "Tinggalkan pesan", "value": "tinggalkan pesan"},
            {"id": "wait_in_lobby", "label": "Tunggu di lobby", "value": "tunggu di lobby"},
            {"id": "decline", "label": "Batal", "value": "tidak jadi"},
        ],
    )


def _build_contact_request_success_answer(selected: dict, action_result: dict[str, Any]) -> str:
    detail = str(action_result.get("detail") or "").strip()
    if detail:
        return detail

    action_type = str(action_result.get("type") or "").strip().lower()
    if action_type == "call":
        return (
            f"Permintaan panggilan untuk {selected['nama']} sudah diteruskan. "
            "Silakan menunggu sebentar di area resepsionis."
        )

    return (
        f"Permintaan kontak untuk {selected['nama']} sudah diterima. "
        "Silakan lanjutkan instruksi berikutnya."
    )


def _is_unavailable_contact_status(status: str) -> bool:
    return status in {"busy", "unavailable", "offline", "not_available", "no_response"}


def _is_successful_contact_status(status: str) -> bool:
    return status in {"queued", "ringing", "connected", "sent", "sent_dummy"}


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
        stored_call: dict[str, Any] | None = None
        initial_call_provider = (
            "dummy"
            if str(getattr(settings, "app_env", "development") or "development").strip().lower() != "production"
            else ("twilio" if "twilio.com" in str(getattr(settings, "contact_call_api_url", "") or "").lower() else "contact_call_api")
        )
        try:
            stored_call = AdminRepository.create_contact_call(
                employee_id=int(employee["id"]),
                employee_nama=str(employee["nama"]),
                employee_departemen=str(employee["departemen"]),
                employee_nomor_wa=str(employee["nomor_wa"]),
                call_status="queued",
                call_detail="Menunggu dispatcher call.",
                call_provider=initial_call_provider,
            )
            dispatch_result = queue_contact_call(employee=employee)
            delivered_payload = AdminRepository.update_contact_call_status(
                call_id=int(stored_call["id"]),
                call_status=str(dispatch_result.get("status") or "queued"),
                call_detail=str(dispatch_result.get("detail") or "Permintaan panggilan sedang diproses."),
                call_provider=str(dispatch_result.get("provider") or "dummy"),
                provider_call_id=str(
                    dispatch_result.get("provider_call_id")
                    or dispatch_result.get("provider_message_id")
                    or ""
                ),
                provider_payload=dispatch_result.get("provider_payload"),
                mark_connected=str(dispatch_result.get("status") or "").strip().lower() == "connected",
            )
        except Exception:
            if stored_call and stored_call.get("id"):
                try:
                    AdminRepository.update_contact_call_status(
                        call_id=int(stored_call["id"]),
                        call_status="failed",
                        call_detail="Dispatcher call gagal dijalankan.",
                        call_provider=initial_call_provider,
                        provider_payload={"error": "dispatch_failed"},
                        mark_connected=False,
                    )
                except Exception:
                    _logger.exception("chat.contact call failure update failed")
            raise

        return {
            "type": "call",
            "status": str((delivered_payload or {}).get("call_status") or dispatch_result.get("status") or "queued"),
            "provider": str((delivered_payload or {}).get("call_provider") or dispatch_result.get("provider") or "dummy"),
            "employee": {
                "id": employee["id"],
                "nama": employee["nama"],
                "departemen": employee["departemen"],
                "jabatan": employee["jabatan"],
            },
            "detail": str((delivered_payload or {}).get("call_detail") or dispatch_result.get("detail") or ""),
            "provider_payload": dispatch_result.get("provider_payload"),
            "call": delivered_payload,
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


def _initial_message_delivery_provider() -> str:
    app_env = str(getattr(settings, "app_env", "development") or "development").strip().lower()
    return "whatsapp_api" if app_env == "production" else "dummy"


def _build_stage(stage: str, flow_context: dict, **kwargs: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"stage": stage, "context": flow_context}
    result.update(kwargs)
    return result


# --- Handler helpers ---

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


def _expired_response(conversation_id: str | None, flow_context: dict, msg: str) -> dict:
    """Kembalikan response 'sesi berakhir' dan reset ke idle."""
    store_chat_message(conversation_id, "assistant", msg)
    return _build_contact_response(
        answer=msg,
        conversation_id=conversation_id,
        flow_state=_build_stage("idle", flow_context),
    )


# ============================================================================
# LANGKAH 3: STAGE DISAMBIGUATION
# ============================================================================


def _handle_stage_disambiguation(ctx: dict) -> dict:
    user_message, conversation_id, safe_flow_state, flow_context, action = _unpack_ctx(ctx)

    candidates = safe_flow_state.get("candidates") or []
    if not isinstance(candidates, list) or not candidates:
        return _expired_response(conversation_id, flow_context, "Pilihan kandidat sudah kedaluwarsa. Silakan sebutkan lagi siapa karyawan yang ingin dihubungi.")

    selected = _resolve_disambiguation_selection(user_message, candidates)
    if not selected:
        if len(candidates) == 1 and isinstance(candidates[0], dict) and candidates[0].get("id"):
            selected = candidates[0]
            answer = f"Apakah Anda ingin menghubungi {_format_employee_contact_target(selected)}?"
            store_chat_message(conversation_id, "assistant", answer)
            return _build_contact_response(
                answer=answer,
                conversation_id=conversation_id,
                flow_state=_build_stage("await_confirmation", flow_context, action=action, selected=selected),
                follow_up=_build_confirmation_follow_up(),
            )

        answer = _build_disambiguation_prompt(candidates, "Saya menemukan beberapa kandidat yang mirip.")
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage("await_disambiguation", flow_context, action=action, candidates=candidates),
            follow_up=_build_disambiguation_follow_up(candidates),
        )

    answer = f"Apakah Anda ingin menghubungi {_format_employee_contact_target(selected)}?"
    store_chat_message(conversation_id, "assistant", answer)
    return _build_contact_response(
        answer=answer,
        conversation_id=conversation_id,
        flow_state=_build_stage("await_confirmation", flow_context, action=action, selected=selected),
        follow_up=_build_confirmation_follow_up(),
    )


# ============================================================================
# LANGKAH 4: STAGE UNAVAILABLE CHOICE
# ============================================================================


def _handle_stage_unavailable_choice(ctx: dict) -> dict:
    user_message, conversation_id, safe_flow_state, flow_context, action = _unpack_ctx(ctx)
    selected, target_kind, department = _extract_session(safe_flow_state)

    if not isinstance(selected, dict) or not selected.get("id"):
        return _expired_response(conversation_id, flow_context, "Sesi tidak tersedia berakhir. Silakan ulangi permintaan hubungi karyawan.")

    choice_decision = _classify_unavailable_choice_rule_based(user_message)
    if choice_decision == "unknown":
        choice_result = interpret_unavailable_choice(user_message, safe_flow_state)
        choice_decision = str(choice_result.get("decision") or "unknown").strip().lower()

    if choice_decision == "leave_message":
        answer = "Baik, saya bantu tinggalkan pesan. Mohon sebutkan nama Anda terlebih dahulu."
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage("await_message_name", flow_context, action=action, selected=selected, target_kind=target_kind, department=department),
        )

    if choice_decision == "decline":
        answer = "Baik, Anda tidak meninggalkan pesan. Silakan menuju front office untuk bantuan lebih lanjut secara offline."
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_build_stage("idle", flow_context))

    if choice_decision == "wait_in_lobby":
        answer = (
            f"Baik, silakan sebutkan nama Anda. "
            f"Saya akan menyampaikan kepada {selected['nama']} bahwa Anda menunggu di lobby."
        )
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage("await_waiter_name", flow_context, action=action, selected=selected, target_kind=target_kind, department=department),
        )

    answer = _build_unavailable_contact_answer(selected, target_kind, department)
    store_chat_message(conversation_id, "assistant", answer)
    return _build_contact_response(
        answer=answer,
        conversation_id=conversation_id,
        flow_state=_build_stage("await_unavailable_choice", flow_context, action=action, selected=selected, target_kind=target_kind, department=department),
        follow_up=_build_unavailable_follow_up(),
    )


# ============================================================================
# LANGKAH 5: STAGE CONFIRMATION
# ============================================================================


def _handle_stage_confirmation(ctx: dict) -> dict:
    user_message, conversation_id, safe_flow_state, flow_context, action = _unpack_ctx(ctx)
    selected, target_kind, department = _extract_session(safe_flow_state)
    candidates = safe_flow_state.get("candidates") or []

    if target_kind == "department" and (not isinstance(selected, dict) or not selected.get("id")):
        if isinstance(candidates, list) and candidates:
            selected = candidates[0]
        elif department:
            dept_matches = _find_department_candidates(department)
            selected = dept_matches[0] if dept_matches else {}

    if not isinstance(selected, dict) or not selected.get("id"):
        return _expired_response(conversation_id, flow_context, "Sesi konfirmasi sudah berakhir. Silakan ulangi permintaan hubungi karyawan.")

    current_intent = _classify_confirmation_reply(user_message)
    if current_intent == "confirm_no":
        if target_kind == "person" and isinstance(candidates, list) and len(candidates) > 1:
            remaining_candidates = [
                item for item in candidates
                if str(item.get("id") or "") != str(selected.get("id") or "")
            ]
            if remaining_candidates:
                if len(remaining_candidates) == 1 and isinstance(remaining_candidates[0], dict) and remaining_candidates[0].get("id"):
                    fallback_selected = remaining_candidates[0]
                    answer = f"Baik, bagaimana jika {_format_employee_contact_target(fallback_selected)}?"
                    store_chat_message(conversation_id, "assistant", answer)
                    return _build_contact_response(
                        answer=answer,
                        conversation_id=conversation_id,
                        flow_state=_build_stage(
                            "await_confirmation", flow_context,
                            action=action,
                            selected=fallback_selected,
                            target_kind="person",
                            candidates=remaining_candidates,
                        ),
                        follow_up=_build_confirmation_follow_up(),
                    )

                answer = _build_disambiguation_prompt(remaining_candidates, "Baik, saya carikan kandidat lain yang paling mirip.")
                store_chat_message(conversation_id, "assistant", answer)
                return _build_contact_response(
                    answer=answer,
                    conversation_id=conversation_id,
                    flow_state=_build_stage("await_disambiguation", flow_context, action=action, candidates=remaining_candidates),
                    follow_up=_build_disambiguation_follow_up(remaining_candidates),
                )

        answer = _build_cancel_contact_answer(selected, target_kind, department)
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_build_stage("idle", flow_context))

    if current_intent != "confirm_yes":
        answer = (
            "Silakan jawab terlebih dahulu, apakah Anda ingin melanjutkan hubungi "
            f"{selected['nama']} ({selected['departemen']})?"
        )
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage("await_confirmation", flow_context, action=action, selected=selected, target_kind=target_kind, department=department, candidates=candidates),
            follow_up=_build_confirmation_follow_up(),
        )

    try:
        action_result = _start_contact_request(selected, action)
    except Exception:
        _logger.exception("chat.contact action dispatch failed")
        answer = "Maaf, sistem belum berhasil memproses permintaan hubungi saat ini."
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_build_stage("idle", flow_context))

    request_status = str(action_result.get("status") or "").strip().lower()

    if action == "notify":
        answer = (
            f"Baik, saya bantu sampaikan pesan untuk {selected['nama']}. "
            "Mohon sebutkan nama Anda terlebih dahulu."
        )
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage(
                "await_message_name",
                flow_context,
                action=action,
                selected=selected,
                target_kind=target_kind,
                department=department,
            ),
            action_result=action_result,
        )

    if _is_unavailable_contact_status(request_status):
        answer = _build_unavailable_contact_answer(selected, target_kind, department)
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage(
                "await_unavailable_choice",
                flow_context,
                action=action,
                selected=selected,
                target_kind=target_kind,
                department=department,
            ),
            action_result=action_result,
            follow_up=_build_unavailable_follow_up(),
        )

    if _is_successful_contact_status(request_status):
        answer = _build_contact_request_success_answer(selected, action_result)
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage("idle", flow_context),
            action_result=action_result,
        )

    answer = "Permintaan hubungi belum berhasil diproses. Silakan coba lagi atau lanjutkan melalui front office."
    store_chat_message(conversation_id, "assistant", answer)
    return _build_contact_response(
        answer=answer,
        conversation_id=conversation_id,
        flow_state=_build_stage("idle", flow_context),
        action_result=action_result,
    )


# ============================================================================
# LANGKAH 6: STAGE WAITER NAME
# ============================================================================


def _handle_stage_waiter_name(ctx: dict) -> dict:
    user_message, conversation_id, safe_flow_state, flow_context, action = _unpack_ctx(ctx)
    selected, target_kind, department = _extract_session(safe_flow_state)

    if not isinstance(selected, dict) or not selected.get("id"):
        return _expired_response(conversation_id, flow_context, "Sesi menunggu berakhir. Silakan ulangi permintaan hubungi karyawan.")

    visitor_name = extract_visitor_name(user_message, safe_flow_state)
    if not visitor_name:
        answer = "Silakan sebutkan nama Anda terlebih dahulu."
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage("await_waiter_name", flow_context, action=action, selected=selected, target_kind=target_kind, department=department),
        )

    answer = f"Baik, {visitor_name}. Saya akan menyampaikan kepada {selected['nama']} bahwa Anda menunggu di lobby."
    store_chat_message(conversation_id, "assistant", answer)
    return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_build_stage("idle", flow_context))


# ============================================================================
# LANGKAH 7: STAGE MESSAGE NAME
# ============================================================================


def _handle_stage_message_name(ctx: dict) -> dict:
    user_message, conversation_id, safe_flow_state, flow_context, action = _unpack_ctx(ctx)
    selected, target_kind, department = _extract_session(safe_flow_state)

    if not isinstance(selected, dict) or not selected.get("id"):
        return _expired_response(conversation_id, flow_context, "Sesi pesan berakhir. Silakan ulangi permintaan hubungi karyawan.")

    visitor_name = extract_visitor_name(user_message, safe_flow_state)
    if not visitor_name:
        answer = "Mohon sebutkan nama Anda terlebih dahulu agar saya bisa mencatat pesannya."
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage("await_message_name", flow_context, action=action, selected=selected, target_kind=target_kind, department=department),
        )

    answer = f"Terima kasih, {visitor_name}. Sekarang mohon sampaikan tujuan atau keperluan Anda."
    store_chat_message(conversation_id, "assistant", answer)
    return _build_contact_response(
        answer=answer,
        conversation_id=conversation_id,
        flow_state=_build_stage("await_message_goal", flow_context, action=action, selected=selected, target_kind=target_kind, department=department, visitor_name=visitor_name),
    )


# ============================================================================
# LANGKAH 8: STAGE MESSAGE GOAL
# ============================================================================


def _handle_stage_message_goal(ctx: dict) -> dict:
    user_message, conversation_id, safe_flow_state, flow_context, action = _unpack_ctx(ctx)
    selected, target_kind, department = _extract_session(safe_flow_state)
    visitor_name = str(safe_flow_state.get("visitor_name") or "").strip()

    if not isinstance(selected, dict) or not selected.get("id"):
        return _expired_response(conversation_id, flow_context, "Sesi pesan berakhir. Silakan ulangi permintaan hubungi karyawan.")

    if not visitor_name:
        answer = "Mohon sebutkan nama Anda terlebih dahulu sebelum menyampaikan tujuan."
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage("await_message_name", flow_context, action=action, selected=selected, target_kind=target_kind, department=department),
        )

    visitor_goal = extract_visitor_goal(user_message, safe_flow_state)
    if len(visitor_goal) < 5:
        answer = "Tujuannya masih terlalu singkat. Mohon jelaskan tujuan Anda dengan lebih lengkap."
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage("await_message_goal", flow_context, action=action, selected=selected, target_kind=target_kind, department=department, visitor_name=visitor_name),
        )

    stored_message: dict[str, Any] | None = None
    initial_message_provider = _initial_message_delivery_provider()
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
            delivery_provider=initial_message_provider,
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
                    delivery_provider=initial_message_provider,
                    provider_payload={"error": "dispatch_failed"},
                    mark_sent=False,
                )
            except Exception:
                _logger.exception("chat.contact message failure update failed")
        answer = "Maaf, pesan belum berhasil dikirim. Silakan menuju front office untuk bantuan offline."
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_build_stage("idle", flow_context))

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
    store_chat_message(conversation_id, "assistant", answer)
    return _build_contact_response(
        answer=answer,
        conversation_id=conversation_id,
        flow_state=_build_stage("idle", flow_context),
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


# ============================================================================
# LANGKAH 9: STAGE ENTRY
# ============================================================================


def _handle_stage_entry(ctx: dict) -> dict:
    user_message, conversation_id, _, flow_context, action = _unpack_ctx(ctx)
    semantic_intent: dict = ctx["semantic_intent"]

    semantic_target_type = str(semantic_intent.get("target_type") or "none").strip().lower()
    semantic_target_value = str(semantic_intent.get("target_value") or "").strip()
    department_target = ""

    if semantic_target_type == "department" and semantic_target_value:
        department_target = _normalize_department_label(semantic_target_value)

    if department_target:
        dept_matches = _find_department_candidates(department_target)
        if not dept_matches:
            answer = f"Saat ini saya belum menemukan staf terdaftar di tim {department_target}."
            store_chat_message(conversation_id, "assistant", answer)
            return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_build_stage("idle", flow_context))

        selected = dept_matches[0]
        answer = f"Tentu, apakah Anda ingin saya menghubungkan Anda dengan tim {department_target}?"
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage("await_confirmation", flow_context, action=action, target_kind="department", department=department_target, selected=selected, candidates=dept_matches[:5]),
            follow_up=_build_confirmation_follow_up(),
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
    matches = _find_employee_candidates(search_query, department_hint=department_hint)

    if not matches:
        answer = "Saya tidak menemukan karyawan tersebut. Silakan sebutkan nama lengkap atau divisinya."
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(answer=answer, conversation_id=conversation_id, flow_state=_build_stage("idle", flow_context))

    if len(matches) == 1:
        selected = matches[0]
        answer = f"Apakah Anda ingin menghubungi {_format_employee_contact_target(selected)}?"
        store_chat_message(conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=conversation_id,
            flow_state=_build_stage("await_confirmation", flow_context, action=action, selected=selected, target_kind="person"),
            follow_up=_build_confirmation_follow_up(),
        )

    candidates = matches
    answer = _build_disambiguation_prompt(candidates, "Saya menemukan beberapa kandidat yang mirip.")
    store_chat_message(conversation_id, "assistant", answer)
    return _build_contact_response(
        answer=answer,
        conversation_id=conversation_id,
        flow_state=_build_stage("await_disambiguation", flow_context, action=action, candidates=candidates),
        follow_up=_build_disambiguation_follow_up(candidates),
    )


# ============================================================================
# LANGKAH 10: PETA STAGE HANDLER
# ============================================================================

_STAGE_HANDLERS: dict[str, Any] = {
    "await_disambiguation": _handle_stage_disambiguation,
    "await_confirmation": _handle_stage_confirmation,
    "await_unavailable_choice": _handle_stage_unavailable_choice,
    "await_waiter_name": _handle_stage_waiter_name,
    "await_message_name": _handle_stage_message_name,
    "await_message_goal": _handle_stage_message_goal,
}


# ============================================================================
# LANGKAH 11: HELPER ORCHESTRATION
# ============================================================================


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


def _should_detect_contact_intent(
    *,
    user_message: str,
    is_active_stage: bool,
    active_flow_state: dict[str, Any],
) -> bool:
    if not user_message:
        return False

    if not message_may_require_contact_intent(user_message, active_flow_state):
        return False

    if not is_active_stage:
        return True

    active_stage_allows_new_target = (
        _classify_confirmation_reply(user_message) == "unknown"
        and _classify_unavailable_choice_rule_based(user_message) == "unknown"
    )
    return active_stage_allows_new_target


def _is_contact_intent_usable(user_message: str, semantic_intent: dict[str, Any]) -> bool:
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
    fallback_matches = _find_employee_candidates(
        fallback_query,
        department_hint=str(semantic_intent.get("target_department") or "").strip() or extract_department_from_text(user_message) or "",
    )
    return bool(fallback_matches)


# ============================================================================
# LANGKAH 12: ENTRY POINT CONTACT FLOW
# ============================================================================


def handle_contact_flow(
    message: str,
    conversation_id: str | None = None,
    history: list[dict] | None = None,
    flow_state: dict[str, Any] | None = None,
) -> dict:
    resolved_conversation_id, prior_history = _resolve_chat_memory(conversation_id, history=history)
    user_message = (message or "").strip()
    safe_flow_state = flow_state if isinstance(flow_state, dict) else {}
    stage = str(safe_flow_state.get("stage") or "idle").strip().lower()
    is_active_stage = stage in _STAGE_HANDLERS
    base_context = _extract_flow_context(safe_flow_state)
    should_probe_intent_llm = _should_detect_contact_intent(
        user_message=user_message,
        is_active_stage=is_active_stage,
        active_flow_state=safe_flow_state,
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
    action = _resolve_contact_mode(semantic_intent, safe_flow_state, user_message)
    flow_context = _update_flow_context_from_intent(base_context, semantic_intent)

    if not user_message:
        return {
            "handled": False,
            "flow_state": _build_idle_flow_state(flow_context),
            "conversation_id": resolved_conversation_id,
            "history": prior_history,
        }

    semantic_contact_usable = _is_contact_intent_usable(user_message, semantic_intent)

    if _should_restart_contact_flow(
        stage=stage,
        user_message=user_message,
        active_flow_state=safe_flow_state,
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

    store_chat_message(resolved_conversation_id, "user", user_message)

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
    return _handle_stage_entry(ctx)
