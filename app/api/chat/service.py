import json
import logging
import re
import time
from difflib import SequenceMatcher
from typing import Any

from api.admin.repository import AdminRepository
from api.chat.department import extract_department_from_text, normalize_department
from api.chat.intent import (
    detect_conversation_intent,
    extract_visitor_goal,
    extract_visitor_name,
    interpret_unavailable_choice,
    message_may_require_contact_intent,
)
from api.chat.repository import ChatRepository
from config import settings
from integrations.contact_dispatch import dispatch_contact_message, normalize_contact_mode, queue_contact_call
from rag.employee_directory import load_employee_directory
from rag.generate import generate_answer, generate_answer_stream
from rag.retrieve import retrieve_context

_logger = logging.getLogger(__name__)
CHAT_SYSTEM_FALLBACK = "Maaf, sistem sedang mengalami gangguan. Silakan coba lagi sebentar."
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


def _store_chat_message(conversation_id: str | None, role: str, content: str) -> None:
    if not conversation_id:
        return
    try:
        ChatRepository.add_message(conversation_id, role, content)
    except Exception:
        _logger.exception("chat.memory write failed conversation_id=%s role=%s", conversation_id, role)


def _build_answer_payload(answer: str, citations: list[dict], conversation_id: str | None) -> dict:
    payload = {
        "answer": answer,
        "citations": citations,
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    return payload


def _list_knowledge_employees() -> list[dict]:
    try:
        return load_employee_directory()
    except Exception:
        _logger.exception("chat.employee_directory failed to load")
        return []


def _build_employee_context() -> tuple[str, list[dict]]:
    employees = _list_knowledge_employees()

    if not employees:
        return "", []

    lines = [
        f"- {employee['nama']} | Departemen: {employee['departemen']} | Jabatan: {employee['jabatan']} | WA: {employee['nomor_wa']}"
        for employee in employees
    ]
    context = "DATA KARYAWAN TERDAFTAR:\n" + "\n".join(lines)
    citation = {
        "content": context,
        "metadata": {
            "source": "employees-knowledge",
            "path": "knowledge:employees-directory",
            "chunk_index": 0,
        },
        "score": 1.0,
    }
    return context, [citation]


def _build_retrieval_result(message: str, history: list[dict]) -> tuple[dict, float]:
    retrieval_started_at = time.perf_counter()
    try:
        retrieval = retrieve_context(message, history=history)
    except Exception:
        _logger.exception("chat.retrieve failed message=%s", message)
        retrieval = {"context": "", "citations": []}

    retrieval_ms = (time.perf_counter() - retrieval_started_at) * 1000
    return retrieval, retrieval_ms


def _build_grounding_note(retrieval: dict[str, Any]) -> str:
    support = retrieval.get("support") if isinstance(retrieval, dict) else {}
    if not isinstance(support, dict):
        support = {}

    grounding = str(support.get("grounding") or "low").strip().lower()
    if grounding == "high":
        return "Konteks sangat relevan. Jawab singkat dan langsung dengan fakta yang tertulis."
    if grounding == "medium":
        return (
            "Konteks cukup relevan, tetapi mungkin hanya menjawab sebagian. "
            "Pastikan setiap detail spesifik yang disebut memang tertulis eksplisit."
        )
    return (
        "Konteks hanya berkaitan sebagian atau lemah. "
        "Jangan memberikan lokasi, nomor, nama, jadwal, atau detail spesifik kecuali benar-benar tertulis jelas."
    )


def _should_fallback_to_unknown(retrieval: dict[str, Any]) -> bool:
    support = retrieval.get("support") if isinstance(retrieval, dict) else {}
    if not isinstance(support, dict):
        support = {}

    context = str(retrieval.get("context") or "").strip() if isinstance(retrieval, dict) else ""
    citations = retrieval.get("citations") if isinstance(retrieval, dict) else []
    has_citations = isinstance(citations, list) and bool(citations)

    # Jangan fallback jika masih ada konteks/citation yang bisa dijadikan jawaban.
    if context or has_citations:
        return False

    grounding = str(support.get("grounding") or "").strip().lower()
    top_coverage = float(support.get("top_coverage") or 0.0)
    top_bigram_coverage = float(support.get("top_bigram_coverage") or 0.0)
    return grounding == "low" and top_coverage <= 0.05 and top_bigram_coverage <= 0.0


def _normalize_text(value: str) -> str:
    return " ".join((value or "").lower().split())


_RETRIEVAL_STOPWORDS = {
    "ada",
    "adalah",
    "apa",
    "apakah",
    "atau",
    "bagaimana",
    "berapa",
    "dalam",
    "dan",
    "dari",
    "dengan",
    "di",
    "dimana",
    "di mana",
    "hari",
    "ini",
    "itu",
    "kalau",
    "ke",
    "keadaan",
    "kerja",
    "mana",
    "mohon",
    "saja",
    "saya",
    "silakan",
    "tentang",
    "tolong",
    "untuk",
    "yang",
}


def _tokenize_for_retrieval(text: str) -> list[str]:
    normalized = _normalize_text(text)
    return re.findall(r"[a-z0-9]+", normalized)


def _informative_tokens(text: str) -> list[str]:
    return [
        token
        for token in _tokenize_for_retrieval(text)
        if len(token) > 1 and token not in _RETRIEVAL_STOPWORDS
    ]


def _candidate_overlap_score(query: str, candidate: str) -> float:
    query_tokens = _informative_tokens(query)
    if not query_tokens:
        return 0.0

    candidate_text = _normalize_text(candidate)
    candidate_tokens = set(_tokenize_for_retrieval(candidate_text))
    if not candidate_tokens:
        return 0.0

    overlap = sum(1 for token in query_tokens if token in candidate_tokens)
    coverage = overlap / max(1, len(query_tokens))
    bigram_hits = 0
    if len(query_tokens) > 1:
        bigrams = [f"{left} {right}" for left, right in zip(query_tokens, query_tokens[1:])]
        bigram_hits = sum(1 for gram in bigrams if gram in candidate_text)
        coverage += (bigram_hits / max(1, len(bigrams))) * 0.18

    return coverage


def _cleanup_structured_answer(text: str) -> str:
    cleaned = " ".join((text or "").replace("|", " | ").split()).strip(" ,;:")
    if not cleaned:
        return ""
    if cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned


def _extract_structured_candidates(citations: list[dict]) -> list[dict[str, str | float]]:
    candidates: list[dict[str, str | float]] = []

    for citation in citations:
        content = str(citation.get("content") or "").strip()
        if not content:
            continue

        lines = [line.strip() for line in content.splitlines() if line.strip()]
        section_context: list[str] = []

        for line in lines:
            faq_matches = list(re.finditer(r"([^|?]{0,120}\?)\s*\|\s*(.+?)(?=(?:\s+[^|?]{0,120}\?\s*\|)|$)", line))
            if faq_matches:
                for match in faq_matches:
                    label = match.group(1).strip()
                    value = match.group(2).strip()
                    context_text = " ".join([*section_context[-2:], label, value]).strip()
                    candidates.append(
                        {
                            "label": label,
                            "value": value,
                            "context": context_text,
                            "kind": "faq",
                        }
                    )
                continue

            if "|" in line:
                parts = [part.strip() for part in line.split("|") if part.strip()]
                if len(parts) >= 2:
                    label = parts[0]
                    value = " | ".join(parts[1:]).strip()
                    context_text = " ".join([*section_context[-2:], label, value]).strip()
                    candidates.append(
                        {
                            "label": label,
                            "value": value,
                            "context": context_text,
                            "kind": "field",
                        }
                    )
                    continue

            section_context.append(line)
            if len(section_context) > 3:
                section_context = section_context[-3:]

    return candidates


def _fallback_answer_from_retrieval(message: str, retrieval: dict[str, Any]) -> str:
    citations = retrieval.get("citations") if isinstance(retrieval, dict) else []
    if not isinstance(citations, list) or not citations:
        return ""

    best_candidate: dict[str, str | float] | None = None
    best_score = 0.0
    for candidate in _extract_structured_candidates(citations):
        score = _candidate_overlap_score(message, str(candidate.get("context") or ""))
        if str(candidate.get("kind") or "") == "faq":
            score += 0.08
        if score > best_score:
            best_score = score
            best_candidate = candidate

    if not best_candidate or best_score < 0.42:
        return ""

    label = str(best_candidate.get("label") or "").strip()
    value = str(best_candidate.get("value") or "").strip()
    kind = str(best_candidate.get("kind") or "").strip()

    if kind == "faq":
        return _cleanup_structured_answer(value)

    answer = f"{label}: {value}"
    return _cleanup_structured_answer(answer)


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


_EMPLOYEE_FUZZY_THRESHOLD = 0.28


def _similarity(a: str, b: str) -> float:
    """Hitung kemiripan dua string menggunakan SequenceMatcher."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _normalize_department_label(value: str) -> str:
    """Delegasikan ke modul shared."""
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
    confidence = float(intent_result.get("confidence") or 0.0)
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
    """
    Hitung skor kemiripan antara query dan data karyawan.

    Menggabungkan beberapa sinyal:
    - similarity nama penuh vs query
    - similarity per-token (nama depan, dst)
    - similarity departemen dan jabatan
    - substring containment sebagai boost tambahan

    Tidak membutuhkan exact match — typo ringan dan nama panggilan
    tetap bisa ditemukan.
    """
    nq = _normalize_text(query)
    if not nq:
        return 1.0

    nama = _normalize_text(str(employee.get("nama", "")))
    dept = _normalize_text(str(employee.get("departemen", "")))
    jabatan = _normalize_text(str(employee.get("jabatan", "")))

    # Similarity nama penuh
    score_nama = _similarity(nq, nama)

    # Similarity tiap token nama (misal: hanya sebut nama depan)
    nama_tokens = nama.split()
    token_scores = [_similarity(nq, t) for t in nama_tokens] if nama_tokens else [0.0]
    score_token_name = max(token_scores)

    # Containment: apakah query ada sebagai substring di nama
    score_contains = 0.75 if nq in nama else 0.0

    # Similarity departemen dan jabatan (bobot lebih rendah)
    score_dept = _similarity(nq, dept) * 0.65
    score_jabatan = _similarity(nq, jabatan) * 0.55

    return max(score_nama, score_token_name, score_contains, score_dept, score_jabatan)


def _search_employees(query: str, department_hint: str = "") -> list[dict]:
    """
    Cari karyawan yang paling cocok dengan query menggunakan fuzzy scoring.
    Mengembalikan daftar terurut dari yang paling relevan.
    """
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

    scored.sort(
        key=lambda item: (
            -item[1],
            _normalize_text(str(item[0].get("nama", ""))),
        )
    )
    matches = [emp for emp, _ in scored]

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
        option_names = [_format_employee_name_department(item) for item in candidates[:3] if item.get("nama")]
        answer = "Saya menemukan beberapa karyawan bernama serupa."
        if len(option_names) == 1:
            answer += f" Apakah {option_names[0]}?"
        elif len(option_names) == 2:
            answer += f" Apakah {option_names[0]} atau {option_names[1]}?"
        elif len(option_names) >= 3:
            answer += f" Apakah {option_names[0]}, {option_names[1]}, atau {option_names[2]}?"
        else:
            answer += " Silakan sebutkan nama lengkap karyawan yang ingin dihubungi."
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

    candidates = matches[:5]
    option_names = [_format_employee_name_department(item) for item in candidates[:3] if item.get("nama")]
    answer = "Saya menemukan beberapa karyawan bernama serupa."
    if option_names:
        if len(option_names) == 1:
            answer += f" Apakah {option_names[0]}?"
        elif len(option_names) == 2:
            answer += f" Apakah {option_names[0]} atau {option_names[1]}?"
        else:
            answer += f" Apakah {option_names[0]}, {option_names[1]}, atau {option_names[2]}?"
    _store_chat_message(conversation_id, "assistant", answer)
    return _build_contact_response(
        answer=answer,
        conversation_id=conversation_id,
        flow_state=_state("await_disambiguation", action=action, candidates=candidates),
    )


_STAGE_HANDLERS: dict[str, Any] = {
    "await_disambiguation":           _handle_await_disambiguation,
    "await_confirmation":             _handle_await_confirmation,
    "contacting_unavailable_pending": _handle_contacting_unavailable_pending,
    "await_unavailable_choice":       _handle_await_unavailable_choice,
    "await_waiter_name":              _handle_await_waiter_name,
    "await_message_name":             _handle_await_message_name,
    "await_message_goal":             _handle_await_message_goal,
}


class ChatAppService:
    @staticmethod
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
        active_stage_allows_new_target = (
            is_active_stage
            and _classify_confirmation_text(user_message) == "unknown"
            and _classify_unavailable_choice_fast(user_message) == "unknown"
        )
        should_probe_intent_llm = (
            not is_internal_timeout_event
            and message_may_require_contact_intent(user_message, safe_flow_state)
            and (not is_active_stage or active_stage_allows_new_target)
        )
        semantic_intent = (
            detect_conversation_intent(
                user_message,
                flow_state=safe_flow_state,
                allow_llm=True,
            )
            if should_probe_intent_llm
            else {
                "intent": "unknown",
                "confidence": 0.0,
                "target_type": "none",
                "target_value": "",
                "action": "none",
                "contact_mode": "auto",
                "search_phrase": "",
            }
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

        semantic_target_type = str(semantic_intent.get("target_type") or "none").strip().lower()
        semantic_target_value = str(semantic_intent.get("target_value") or "").strip()
        semantic_action = str(semantic_intent.get("action") or "none").strip().lower()
        semantic_contact_detected = (
            str(semantic_intent.get("intent") or "").strip().lower() == "contact_employee"
        )
        semantic_contact_has_explicit_target = (
            semantic_target_type in {"person", "department"}
            and bool(semantic_target_value)
        )
        semantic_contact_has_resolved_candidate = False
        if semantic_contact_detected and semantic_action == "contact" and not semantic_contact_has_explicit_target:
            fallback_query = str(semantic_intent.get("search_phrase") or "").strip() or user_message
            fallback_matches = _search_employees(
                fallback_query,
                department_hint=str(semantic_intent.get("target_department") or "").strip() or extract_department_from_text(user_message) or "",
            )
            semantic_contact_has_resolved_candidate = bool(fallback_matches)

        semantic_contact_usable = semantic_contact_detected and semantic_action == "contact" and (
            semantic_contact_has_explicit_target
            or semantic_contact_has_resolved_candidate
        )

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

    @staticmethod
    def ask(
        message: str,
        conversation_id: str | None = None,
        history: list[dict] | None = None,
        flow_state: dict[str, Any] | None = None,
    ) -> dict:
        started_at = time.perf_counter()
        contact_result = ChatAppService.handle_contact_flow(
            message,
            conversation_id=conversation_id,
            history=history,
            flow_state=flow_state,
        )
        if contact_result.get("handled"):
            payload = _build_answer_payload(
                str(contact_result.get("answer") or "").strip(),
                [],
                contact_result.get("conversation_id"),
            )
            payload["handled"] = True
            payload["flow_state"] = contact_result.get("flow_state") or {"stage": "idle"}
            if contact_result.get("action"):
                payload["action"] = contact_result["action"]
            if contact_result.get("follow_up"):
                payload["follow_up"] = contact_result["follow_up"]
            return payload

        resolved_conversation_id = contact_result.get("conversation_id")
        prior_history: list[dict] = contact_result.get("history") or []
        try:
            _store_chat_message(resolved_conversation_id, "user", message)

            retrieval, retrieval_ms = _build_retrieval_result(message, prior_history)

            if _should_fallback_to_unknown(retrieval):
                answer = "Maaf, saya belum menemukan informasi pastinya di knowledge yang tersedia."
                _store_chat_message(resolved_conversation_id, "assistant", answer)
                payload = _build_answer_payload(answer, retrieval["citations"], resolved_conversation_id)
                payload["handled"] = False
                payload["flow_state"] = contact_result.get("flow_state") or {"stage": "idle"}
                return payload

            answer_started_at = time.perf_counter()
            answer = generate_answer(
                message,
                retrieval["context"],
                history=prior_history,
                grounding_note=_build_grounding_note(retrieval),
            )
            answer_ms = (time.perf_counter() - answer_started_at) * 1000
            _store_chat_message(resolved_conversation_id, "assistant", answer)

            elapsed_ms = (time.perf_counter() - started_at) * 1000
            _logger.info(
                "chat.ask route=rag conversation_id=%s retrieval_ms=%.1f answer_ms=%.1f total_ms=%.1f",
                resolved_conversation_id,
                retrieval_ms,
                answer_ms,
                elapsed_ms,
            )
            payload = _build_answer_payload(answer, retrieval["citations"], resolved_conversation_id)
            payload["handled"] = False
            payload["flow_state"] = contact_result.get("flow_state") or {"stage": "idle"}
            return payload
        except Exception:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            _logger.exception(
                "chat.ask route=rag failed conversation_id=%s total_ms=%.1f",
                resolved_conversation_id,
                elapsed_ms,
            )
            payload = _build_answer_payload(CHAT_SYSTEM_FALLBACK, [], resolved_conversation_id)
            payload["handled"] = False
            payload["flow_state"] = contact_result.get("flow_state") or {"stage": "idle"}
            return payload

    @staticmethod
    def ask_stream(
        message: str,
        conversation_id: str | None = None,
        history: list[dict] | None = None,
        flow_state: dict[str, Any] | None = None,
    ):
        started_at = time.perf_counter()
        contact_result = ChatAppService.handle_contact_flow(
            message,
            conversation_id=conversation_id,
            history=history,
            flow_state=flow_state,
        )
        if contact_result.get("handled"):
            handled_answer = str(contact_result.get("answer") or "").strip()
            handled_conversation_id = contact_result.get("conversation_id")
            handled_flow_state = contact_result.get("flow_state") or {"stage": "idle"}
            handled_action = contact_result.get("action")
            handled_follow_up = contact_result.get("follow_up")

            def _contact_events():
                meta_payload = {
                    "type": "meta",
                    "route": "contact_flow",
                    "flow_state": handled_flow_state,
                }
                if handled_conversation_id:
                    meta_payload["conversation_id"] = handled_conversation_id
                yield json.dumps(meta_payload, ensure_ascii=False) + "\n"
                if handled_action:
                    yield json.dumps({"type": "action", "value": handled_action}, ensure_ascii=False) + "\n"
                if handled_answer:
                    yield json.dumps({"type": "token", "value": handled_answer}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "citations", "value": []}, ensure_ascii=False) + "\n"
                if handled_follow_up:
                    yield json.dumps({"type": "follow_up", "value": handled_follow_up}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"

            return _contact_events()

        resolved_conversation_id = contact_result.get("conversation_id")
        prior_history: list[dict] = contact_result.get("history") or []

        _store_chat_message(resolved_conversation_id, "user", message)

        retrieval, retrieval_ms = _build_retrieval_result(message, prior_history)

        def _events():
            collected_tokens: list[str] = []
            try:
                meta_payload = {
                    "type": "meta",
                    "route": "rag",
                    "flow_state": contact_result.get("flow_state") or {"stage": "idle"},
                }
                if resolved_conversation_id:
                    meta_payload["conversation_id"] = resolved_conversation_id
                yield json.dumps(meta_payload, ensure_ascii=False) + "\n"

                if _should_fallback_to_unknown(retrieval):
                    fallback_answer = "Maaf, saya belum menemukan informasi pastinya di knowledge yang tersedia."
                    _store_chat_message(resolved_conversation_id, "assistant", fallback_answer)
                    yield json.dumps({"type": "token", "value": fallback_answer}, ensure_ascii=False) + "\n"
                    yield json.dumps({"type": "citations", "value": retrieval["citations"]}, ensure_ascii=False) + "\n"
                    yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
                    return

                first_token_logged = False
                for token in generate_answer_stream(
                    message,
                    retrieval["context"],
                    history=prior_history,
                    grounding_note=_build_grounding_note(retrieval),
                ):
                    if not first_token_logged and token:
                        first_token_ms = (time.perf_counter() - started_at) * 1000
                        _logger.info(
                            "chat.stream route=rag conversation_id=%s retrieval_ms=%.1f first_token_ms=%.1f",
                            resolved_conversation_id,
                            retrieval_ms,
                            first_token_ms,
                        )
                        first_token_logged = True
                    if token:
                        collected_tokens.append(token)
                    yield json.dumps({"type": "token", "value": token}, ensure_ascii=False) + "\n"
                final_answer = "".join(collected_tokens).strip()
                if final_answer:
                    _store_chat_message(resolved_conversation_id, "assistant", final_answer)
                yield json.dumps({"type": "citations", "value": retrieval["citations"]}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
            except Exception:
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                _logger.exception(
                    "chat.stream route=rag failed conversation_id=%s retrieval_ms=%.1f total_ms=%.1f",
                    resolved_conversation_id,
                    retrieval_ms,
                    elapsed_ms,
                )
                yield json.dumps(
                    {"type": "error", "value": CHAT_SYSTEM_FALLBACK},
                    ensure_ascii=False,
                ) + "\n"

        return _events()
