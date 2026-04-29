import json
import logging
import re
from typing import Any

from config import settings
from shared.utils.text import normalize_text
from infrastructure.ai_client import generate_text
from modules.chat.constants import (
    DECISION_ANSWER_KNOWLEDGE,
    DECISION_CANCEL_PENDING_ACTION,
    DECISION_CONFIRM_NO,
    DECISION_CONFIRM_YES,
    DECISION_CONTINUE_PENDING_ACTION,
    DECISION_START_CONTACT_MESSAGE,
    DECISION_UNKNOWN,
)
from modules.chat.utils.slots import (
    KNOWN_DEPARTMENTS,
    classify_confirmation_reply,
    extract_department_from_text,
    is_cancel_message,
    is_continue_message,
    normalize_contact_mode,
    normalize_department,
)
from modules.tools.registry import get_tool


_logger = logging.getLogger(__name__)

_DIRECT_CONTACT_VERB_PATTERNS = (
    r"\bhubungi\b",
    r"\bkontak\b",
    r"\bsambung(?:kan)?\b",
    r"\bhubung(?:kan)?\b",
    r"\btelepon\b",
    r"\btelpon\b",
    r"\bcall\b",
    r"\bpanggil(?:kan)?\b",
    r"\bketemu\b",
    r"\bbertemu\b",
    r"\btemui\b",
    r"\bjumpa\b",
    r"\bngobrol(?:\s+(?:dengan|sama))?\b",
    r"\bbicara(?:\s+(?:dengan|sama))?\b",
    r"\bwhatsapp\b",
    r"\bwa\b",
    r"\btitip pesan\b",
    r"\bpesan buat\b",
    r"\bsampaikan ke\b",
    r"\bwa ke\b",
    r"\bchat ke\b",
)
_SEARCH_CONTACT_VERB_PATTERNS = (
    r"\bcari\b",
    r"\bmencari\b",
    r"\bnyari(?:in)?\b",
    r"\bcarikan\b",
    r"\bmau cari\b",
    r"\bingin cari\b",
    r"\bperlu cari\b",
)
_VISIT_CONTACT_VERB_PATTERNS = (
    r"\bmau ke\b",
    r"\bingin ke\b",
    r"\bperlu ke\b",
    r"\bbutuh ke\b",
    r"\bkunjung(?:i)?\b",
)
_APPOINTMENT_CONTACT_PATTERNS = (
    r"\bada janji dengan\b",
    r"\bsudah janji dengan\b",
    r"\bjanjian dengan\b",
    r"\bmeeting dengan\b",
    r"\bada urusan dengan\b",
    r"\bada keperluan dengan\b",
)
_CONTACT_MARKER_PATTERNS = (
    *_DIRECT_CONTACT_VERB_PATTERNS,
    *_SEARCH_CONTACT_VERB_PATTERNS,
    *_VISIT_CONTACT_VERB_PATTERNS,
    *_APPOINTMENT_CONTACT_PATTERNS,
)
_DEPARTMENT_CONTEXT_PATTERNS = (
    r"\btim\b",
    r"\bdivisi\b",
    r"\bdepartemen\b",
    r"\bbagian\b",
    r"\bunit\b",
    r"\bbidang\b",
)
_INFO_REQUEST_PATTERNS = (
    r"\binformasi\b",
    r"\binfo\b",
    r"\bjam kerja\b",
    r"\bjam operasional\b",
    r"\bprofil\b",
    r"\bfasilitas\b",
    r"\balamat\b",
    r"\blokasi\b",
)
_GENERAL_QUESTION_PATTERNS = (
    r"\?$",
    r"^(?:apa|siapa|kapan|dimana|di mana|bagaimana|berapa|apakah)\b",
    r"^(?:bisa|boleh|tolong|mohon)\b.+\b(?:jelaskan|beri tahu|sebutkan|informasikan)\b",
    r"\b(?:jam kerja|jam operasional|alamat|lokasi|fasilitas|informasi|info|profil)\b",
)
_PERSON_REFERENCE_PATTERN = re.compile(r"\b(pak|bu|bapak|ibu|mas|mbak)\s+[a-z][a-z\s]{1,40}")
_PEOPLE_REFERENCE_PATTERNS = (
    r"\bkaryawan\b",
    r"\bpegawai\b",
    r"\bstaff\b",
    r"\bstaf\b",
    r"\borang\b",
    r"\bbapak\b",
    r"\bibu\b",
    r"\bpak\b",
    r"\bbu\b",
    r"\bmas\b",
    r"\bmbak\b",
)
_NAME_TOKEN_STOPWORDS = {
    "pak",
    "bu",
    "bapak",
    "ibu",
    "mas",
    "mbak",
}


def _normalize_message(message: str) -> str:
    return " ".join((message or "").lower().split())


def _matches_any_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _strip_person_titles(text: str) -> str:
    return re.sub(r"\b(?:pak|bu|bapak|ibu|mas|mbak)\b", " ", text)


def _name_tokens(value: str) -> list[str]:
    tokens = re.findall(r"[a-z]+", _strip_person_titles(_normalize_message(value)))
    return [token for token in tokens if len(token) >= 3 and token not in _NAME_TOKEN_STOPWORDS]


def _index_employee_name_candidates(employees: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed: list[dict[str, Any]] = []
    for employee in employees:
        canonical_name = str(employee.get("nama", "")).strip()
        normalized_name = _strip_person_titles(_normalize_message(canonical_name)).strip()
        tokens = _name_tokens(canonical_name)
        if not canonical_name or not normalized_name or not tokens:
            continue
        indexed.append(
            {
                "canonical_name": canonical_name,
                "normalized_name": normalized_name,
                "tokens": tokens,
            }
        )
    return indexed


def _search_employee_name_index(message: str) -> list[dict[str, Any]]:
    try:
        employees = get_tool("employee_directory").search_employees(message, limit=8)
    except Exception:
        return []
    return _index_employee_name_candidates(list(employees or []))


def _find_employee_name_reference(message: str, *, allow_single_token: bool) -> str:
    normalized_message = _strip_person_titles(_normalize_message(message)).strip()
    if not normalized_message:
        return ""

    indexed_employees = _search_employee_name_index(normalized_message)
    if not indexed_employees:
        return ""

    for employee in indexed_employees:
        if re.search(rf"\b{re.escape(employee['normalized_name'])}\b", normalized_message):
            return str(employee["canonical_name"])

    message_tokens = _name_tokens(normalized_message)
    if not message_tokens:
        return ""

    ordered_unique_tokens: list[str] = []
    for token in message_tokens:
        if token not in ordered_unique_tokens:
            ordered_unique_tokens.append(token)

    for employee in indexed_employees:
        matched_tokens = [token for token in employee["tokens"] if token in ordered_unique_tokens]
        if len(matched_tokens) >= 2:
            return str(employee["canonical_name"])

    if not allow_single_token:
        return ""

    for token in ordered_unique_tokens:
        for employee in indexed_employees:
            if token in employee["tokens"]:
                return token

    return ""


def _looks_like_info_lookup(message: str) -> bool:
    return _matches_any_pattern(message, _INFO_REQUEST_PATTERNS)


def _looks_like_general_question(message: str) -> bool:
    normalized = _normalize_message(message)
    if not normalized:
        return False
    if classify_confirmation_reply(normalized) != "unknown":
        return False
    return _matches_any_pattern(normalized, _GENERAL_QUESTION_PATTERNS)


def _has_contact_or_seeking_verb(message: str) -> bool:
    return _matches_any_pattern(message, _CONTACT_MARKER_PATTERNS)


def _text_has_department_prefix(text: str) -> bool:
    normalized = _normalize_message(text)
    return _matches_any_pattern(normalized, _DEPARTMENT_CONTEXT_PATTERNS)


def _has_person_or_team_reference(message: str) -> bool:
    return (
        _matches_any_pattern(message, _PEOPLE_REFERENCE_PATTERNS)
        or _PERSON_REFERENCE_PATTERN.search(message) is not None
        or _text_has_department_prefix(message)
    )


def _message_may_start_contact(message: str) -> bool:
    normalized = _normalize_message(message)
    if not normalized:
        return False

    has_contact_verb = _has_contact_or_seeking_verb(normalized)
    has_target_reference = _has_person_or_team_reference(normalized)
    employee_name_reference = ""
    if has_contact_verb or _PERSON_REFERENCE_PATTERN.search(normalized) is not None:
        employee_name_reference = _find_employee_name_reference(
            normalized,
            allow_single_token=has_contact_verb,
        )
    detected_department = extract_department_from_text(normalized)

    if _looks_like_info_lookup(normalized) and not employee_name_reference:
        return False
    if _matches_any_pattern(normalized, _DIRECT_CONTACT_VERB_PATTERNS):
        return True
    if _PERSON_REFERENCE_PATTERN.search(normalized):
        return True
    if has_contact_verb and has_target_reference:
        return True
    if has_contact_verb and employee_name_reference:
        return True
    if detected_department and has_contact_verb and not _looks_like_info_lookup(normalized):
        return True
    return False


def _default_decision(intent: str = DECISION_ANSWER_KNOWLEDGE) -> dict[str, Any]:
    return {
        "intent": intent,
        "confidence": 0.0,
        "target_type": "none",
        "target_value": "",
        "target_department": "",
        "contact_mode": "auto",
        "search_phrase": "",
        "visitor_name": "",
        "visitor_goal": "",
    }


def _extract_json_object(raw: str) -> dict | None:
    content = (raw or "").strip()
    if not content:
        return None

    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    start_idx = content.find("{")
    end_idx = content.rfind("}")
    if start_idx < 0 or end_idx <= start_idx:
        return None

    try:
        parsed = json.loads(content[start_idx : end_idx + 1])
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _clamp_confidence(raw_value: Any) -> float:
    try:
        confidence = float(raw_value)
    except Exception:
        confidence = 0.0
    return max(0.0, min(1.0, confidence))


def _normalize_decision_payload(payload: dict | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _default_decision(DECISION_UNKNOWN)

    intent = str(payload.get("intent") or DECISION_UNKNOWN).strip().lower()
    if intent not in {
        DECISION_ANSWER_KNOWLEDGE,
        DECISION_START_CONTACT_MESSAGE,
        DECISION_CONTINUE_PENDING_ACTION,
        DECISION_CANCEL_PENDING_ACTION,
        DECISION_CONFIRM_YES,
        DECISION_CONFIRM_NO,
        DECISION_UNKNOWN,
    }:
        intent = DECISION_UNKNOWN

    target_type = str(payload.get("target_type") or "none").strip().lower()
    if target_type not in {"department", "person", "none"}:
        target_type = "none"

    target_value = str(payload.get("target_value") or "").strip()
    target_department = str(payload.get("target_department") or "").strip()
    if target_type == "department" and target_value:
        target_value = normalize_department(target_value)
        target_department = target_value
    elif target_type == "person" and target_value:
        canonical = normalize_department(target_value)
        if canonical in KNOWN_DEPARTMENTS:
            target_type = "department"
            target_value = canonical
            target_department = canonical

    if target_department:
        canonical_department = normalize_department(target_department)
        target_department = canonical_department if canonical_department in KNOWN_DEPARTMENTS else ""

    return {
        "intent": intent,
        "confidence": _clamp_confidence(payload.get("confidence", 0.0)),
        "target_type": target_type,
        "target_value": target_value if target_type != "none" else "",
        "target_department": target_department if target_type != "none" else "",
        "contact_mode": normalize_contact_mode(payload.get("contact_mode")),
        "search_phrase": str(payload.get("search_phrase") or "").strip(),
        "visitor_name": str(payload.get("visitor_name") or "").strip(),
        "visitor_goal": str(payload.get("visitor_goal") or "").strip(),
    }


def _post_correct_decision(message: str, result: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_message(message)
    detected_dept = extract_department_from_text(normalized)
    has_contact_verb = _has_contact_or_seeking_verb(normalized)
    employee_name_reference = (
        _find_employee_name_reference(
            normalized,
            allow_single_token=has_contact_verb,
        )
        if has_contact_verb
        else ""
    )

    if detected_dept:
        has_dept_prefix = _text_has_department_prefix(normalized)
        if (has_contact_verb or has_dept_prefix) and not _looks_like_info_lookup(normalized):
            result = dict(result)
            result["intent"] = DECISION_START_CONTACT_MESSAGE
            result["target_type"] = "department"
            result["target_value"] = detected_dept
            result["target_department"] = detected_dept
            result["confidence"] = max(float(result.get("confidence") or 0.0), 0.85)
            return result

    if employee_name_reference and has_contact_verb and not _looks_like_info_lookup(normalized):
        result = dict(result)
        result["intent"] = DECISION_START_CONTACT_MESSAGE
        result["target_type"] = "person"
        result["target_value"] = employee_name_reference
        result["confidence"] = max(float(result.get("confidence") or 0.0), 0.82)

    return result


def _pending_action_context(pending_action: dict[str, Any] | None) -> str:
    if not pending_action:
        return "-"
    return (
        f"type={pending_action.get('type') or '-'}, "
        f"target={pending_action.get('target_label') or '-'}, "
        f"confirmed={bool(pending_action.get('confirmed'))}, "
        f"visitor_name={pending_action.get('visitor_name') or '-'}, "
        f"visitor_goal={pending_action.get('visitor_goal') or '-'}"
    )


def _llm_decision(message: str, pending_action: dict[str, Any] | None = None) -> dict[str, Any]:
    prompt = f"""Tugas: pahami pesan pengunjung di resepsionis virtual dan pilih aksi berikutnya.

PENDING ACTION:
{_pending_action_context(pending_action)}

Balas HANYA JSON valid:
{{
  "intent": "answer_knowledge|start_contact_message|continue_pending_action|cancel_pending_action|confirm_yes|confirm_no|unknown",
  "confidence": 0.0,
  "target_type": "department|person|none",
  "target_value": "",
  "target_department": "",
  "contact_mode": "call|notify|auto",
  "search_phrase": "",
  "visitor_name": "",
  "visitor_goal": ""
}}

Panduan:
- answer_knowledge: user bertanya informasi perusahaan, profil, alamat, fasilitas, jam kerja, atau small talk.
- start_contact_message: user ingin bertemu, dihubungkan, mencari, atau menitip pesan kepada orang/tim.
- continue_pending_action: user memberi data untuk pending action yang sedang berjalan.
- cancel_pending_action: user membatalkan proses kontak.
- confirm_yes / confirm_no: jawaban konfirmasi.
- target_value isi nama orang atau nama divisi jika jelas.
- visitor_name isi hanya nama tamu.
- visitor_goal isi hanya tujuan atau keperluan tamu.
- Jangan ubah pertanyaan informasi umum menjadi contact message.

Pesan pengunjung:
{message}
"""

    max_retries = max(1, int(getattr(settings, "chat_intent_max_retries", 2)))
    timeout_seconds = max(8, int(getattr(settings, "chat_intent_timeout_seconds", 20) or 20))
    last_raw_response = ""

    for attempt in range(1, max_retries + 1):
        try:
            payload = generate_text(
                prompt=prompt,
                system="",
                stream=False,
                temperature=0.0,
                max_tokens=min(260, settings.ollama_num_predict_short + 120),
                timeout=timeout_seconds,
            )
            last_raw_response = str((payload or {}).get("response", "") or "")
            parsed = _extract_json_object(last_raw_response)
            if isinstance(parsed, dict):
                return _normalize_decision_payload(parsed)
        except Exception:
            _logger.exception("chat.decision llm failed attempt=%s", attempt)

    if last_raw_response.strip():
        return _normalize_decision_payload(_extract_json_object(last_raw_response))
    return _default_decision(DECISION_UNKNOWN)


def decide_next_action(
    message: str,
    *,
    pending_action: dict[str, Any] | None = None,
    history: list[dict] | None = None,
) -> dict[str, Any]:
    normalized_message = normalize_text(message)
    if not normalized_message:
        return _default_decision(DECISION_UNKNOWN)

    if pending_action and is_cancel_message(normalized_message):
        return _default_decision(DECISION_CANCEL_PENDING_ACTION)

    if pending_action and is_continue_message(normalized_message):
        return _default_decision(DECISION_CONTINUE_PENDING_ACTION)

    confirmation = classify_confirmation_reply(normalized_message)
    if pending_action and confirmation == "confirm_yes":
        return _default_decision(DECISION_CONFIRM_YES)
    if pending_action and confirmation == "confirm_no":
        return _default_decision(DECISION_CONFIRM_NO)

    may_start_contact = _message_may_start_contact(normalized_message)
    if may_start_contact:
        decision = _llm_decision(normalized_message, pending_action=pending_action)
        if decision["intent"] in {DECISION_UNKNOWN, DECISION_ANSWER_KNOWLEDGE}:
            decision["intent"] = DECISION_START_CONTACT_MESSAGE
        return _post_correct_decision(normalized_message, decision)

    if pending_action and not _looks_like_general_question(normalized_message):
        decision = _llm_decision(normalized_message, pending_action=pending_action)
        if decision["intent"] == DECISION_UNKNOWN:
            decision["intent"] = DECISION_CONTINUE_PENDING_ACTION
        return _post_correct_decision(normalized_message, decision)

    return _default_decision(DECISION_ANSWER_KNOWLEDGE)
