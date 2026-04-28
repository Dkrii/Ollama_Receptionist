import re
from typing import Any

from contacts.employees import load_employee_directory

from .core import _clamp_confidence, _flow_prompt_context, _llm_json, _normalize_contact_mode, _normalize_message
from .department import KNOWN_DEPARTMENTS, extract_department_from_text, normalize_department


INTENT_FALLBACK = {
    "intent": "unknown",
    "confidence": 0.0,
    "target_type": "none",
    "target_value": "",
    "target_department": "",
    "action": "none",
    "contact_mode": "auto",
}


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

_CONTACT_REFERENCE_PATTERNS = (
    r"\borangnya\b",
    r"\borang itu\b",
    r"\btimnya\b",
    r"\btim itu\b",
    r"\byang ngurus\b",
    r"\borang yang ngurus\b",
    r"\bbagian itu\b",
)

_DEPARTMENT_CONTEXT_PATTERNS = (
    r"\btim\b",
    r"\bdivisi\b",
    r"\bdepartemen\b",
    r"\bbagian\b",
    r"\bunit\b",
    r"\bbidang\b",
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
_NAME_TOKEN_STOPWORDS = {
    "pak",
    "bu",
    "bapak",
    "ibu",
    "mas",
    "mbak",
}


def _matches_any_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _strip_person_titles(text: str) -> str:
    return re.sub(r"\b(?:pak|bu|bapak|ibu|mas|mbak)\b", " ", text)


def _name_tokens(value: str) -> list[str]:
    tokens = re.findall(r"[a-z]+", _strip_person_titles(_normalize_message(value)))
    return [token for token in tokens if len(token) >= 3 and token not in _NAME_TOKEN_STOPWORDS]


def _load_employee_name_index() -> list[dict[str, Any]]:
    try:
        employees = load_employee_directory()
    except Exception:
        return []

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


def _find_employee_name_reference(message: str, *, allow_single_token: bool) -> str:
    normalized_message = _strip_person_titles(_normalize_message(message)).strip()
    if not normalized_message:
        return ""

    indexed_employees = _load_employee_name_index()
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


def message_may_require_contact_intent(message: str, flow_state: dict | None = None) -> bool:
    normalized = _normalize_message(message)
    if not normalized:
        return False

    has_contact_verb = _has_contact_or_seeking_verb(normalized)
    has_target_reference = _has_person_or_team_reference(normalized)
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

    context = flow_state.get("context") if isinstance(flow_state, dict) else {}
    last_topic_type = str((context or {}).get("last_topic_type") or "none").strip().lower()
    if last_topic_type in {"department", "person"} and _matches_any_pattern(
        normalized,
        _CONTACT_REFERENCE_PATTERNS,
    ):
        return True

    return False


def _normalize_intent_payload(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return dict(INTENT_FALLBACK)

    intent = str(payload.get("intent") or "unknown").strip().lower()
    if intent not in {"company_info", "contact_employee", "confirm_yes", "confirm_no", "small_talk", "unknown"}:
        intent = "unknown"

    target_type = str(payload.get("target_type") or "none").strip().lower()
    if target_type not in {"department", "person", "none"}:
        target_type = "none"

    target_value = str(payload.get("target_value") or "").strip()
    target_department = str(payload.get("target_department") or "").strip()
    if target_type == "none":
        target_value = ""
        target_department = ""
    elif target_type == "department" and target_value:
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
    elif target_type == "person":
        extracted_department = extract_department_from_text(target_value)
        if extracted_department in KNOWN_DEPARTMENTS:
            target_department = extracted_department

    action = str(payload.get("action") or "none").strip().lower()
    if action not in {"ask", "contact", "confirm", "none"}:
        action = "none"

    raw_search = str(payload.get("search_phrase") or "").strip()
    search_phrase = normalize_department(raw_search) if raw_search else raw_search

    return {
        "intent": intent,
        "confidence": _clamp_confidence(payload.get("confidence", 0.0)),
        "target_type": target_type,
        "target_value": target_value,
        "target_department": target_department,
        "action": action,
        "contact_mode": _normalize_contact_mode(payload.get("contact_mode")),
        "search_phrase": search_phrase,
    }


def _post_correct_intent(message: str, result: dict) -> dict:
    normalized = _normalize_message(message)
    target_type = result.get("target_type", "none")
    action = result.get("action", "none")
    intent = result.get("intent", "unknown")

    detected_dept = extract_department_from_text(normalized)
    has_contact_verb = _has_contact_or_seeking_verb(normalized)
    employee_name_reference = _find_employee_name_reference(
        normalized,
        allow_single_token=has_contact_verb,
    )

    if detected_dept:
        has_dept_prefix = _text_has_department_prefix(normalized)

        if (has_contact_verb or has_dept_prefix) and not _looks_like_info_lookup(normalized):
            result = dict(result)
            result["intent"] = "contact_employee"
            result["target_type"] = "department"
            result["target_value"] = detected_dept
            result["target_department"] = detected_dept
            result["action"] = "contact"
            if result.get("confidence", 0.0) < 0.85:
                result["confidence"] = 0.85
            return result

    if employee_name_reference and has_contact_verb and not _looks_like_info_lookup(normalized):
        result = dict(result)
        result["intent"] = "contact_employee"
        result["target_type"] = "person"
        result["target_value"] = employee_name_reference
        result["action"] = "contact"
        if result.get("confidence", 0.0) < 0.82:
            result["confidence"] = 0.82

    if intent == "contact_employee" and action == "ask" and target_type in {"person", "department"}:
        result = dict(result)
        result["action"] = "contact"
        if result.get("confidence", 0.0) < 0.75:
            result["confidence"] = 0.75

    current_target_type = str(result.get("target_type") or target_type).strip().lower()
    if current_target_type == "person" and detected_dept:
        result = dict(result)
        result["target_department"] = detected_dept

    return result


def detect_conversation_intent(message: str, flow_state: dict | None = None, allow_llm: bool = True) -> dict:
    normalized_message = (message or "").strip()
    if not normalized_message or not allow_llm:
        return dict(INTENT_FALLBACK)

    flow_context = _flow_prompt_context(flow_state)
    prompt = f"""Tugas: analisis pesan pengunjung yang datang ke resepsionis perusahaan.

KONTEKS PERCAKAPAN:
- stage: {flow_context['stage']}
- last_topic_type: {flow_context['last_topic_type']}
- last_topic_value: {flow_context['last_topic_value'] or '-'}
- last_intent: {flow_context['last_intent']}
- selected_name: {flow_context['selected_name'] or '-'}
- selected_department: {flow_context['selected_department'] or '-'}
- selected_position: {flow_context['selected_position'] or '-'}
- saved_action: {flow_context['saved_action'] or '-'}

Balas HANYA JSON valid (tanpa markdown, tanpa teks tambahan):
{{
  \"intent\": \"company_info|contact_employee|confirm_yes|confirm_no|small_talk|unknown\",
  \"confidence\": 0.0,
  \"target_type\": \"department|person|none\",
  \"target_value\": \"\",
  \"target_department\": \"\",
  \"action\": \"ask|contact|confirm|none\",
  \"contact_mode\": \"call|notify|auto\",
  \"search_phrase\": \"\"
}}

Panduan pengisian:
- Pahami MAKSUD pengunjung secara keseluruhan, bukan cari kata tertentu.
- contact_employee: pengunjung ingin bertemu, dihubungkan, atau menitipkan sesuatu kepada seseorang atau tim/divisi.
- company_info: pengunjung ingin tahu informasi perusahaan, jam kerja, fasilitas, profil, dll.
- confirm_yes / confirm_no: jawaban atas pertanyaan konfirmasi yang sedang aktif.
- small_talk: sapaan, terima kasih, pertanyaan umum di luar topik di atas.

ATURAN PENTING target_type:
- Jika pengunjung menyebut nama DIVISI/TIM/DEPARTEMEN (contoh: \"tim HR\", \"divisi IT\", \"bagian Finance\", \"ke IT\", \"Human Capital\", \"HRD\"), maka target_type HARUS \"department\" dan action HARUS \"contact\".
- Jika pengunjung menyebut nama ORANG (contoh: \"Pak Budi\", \"Bu Sari\"), maka target_type = \"person\".
- Jika pengunjung menyebut nama orang sekaligus divisi/departemennya (contoh: \"Budi dari IT\"), isi target_value dengan nama orangnya dan target_department dengan divisinya.
- Kalimat seperti \"Saya mau ketemu tim HR\" atau \"Saya ingin ke bagian IT\" = contact_employee, target_type=department, action=contact.
- Kalimat seperti \"saya mau cari Budi\", \"tolong carikan Bu Sari\", \"saya ada janji dengan Pak Andi\", \"mau ngobrol sama tim finance\", atau \"bisa panggilkan orang HR\" juga termasuk contact_employee.
- Jika pengguna memakai kata kerja seperti cari, nyari, carikan, ketemu, hubungi, panggilkan, ngobrol dengan, ada janji dengan, atau ada keperluan dengan seseorang/tim, anggap itu sebagai niat menghubungi.

- target_value: nama orang atau divisi yang disebutkan pengunjung (isi jika jelas).
- search_phrase: frasa paling ringkas untuk mencari karyawan - isi jika intent=contact_employee dan target belum eksplisit, kosongkan jika sudah ada di target_value.
- contact_mode: call = minta telepon, notify = minta titip pesan/WA, auto = tidak disebutkan.
- Jika pengguna sedang mencari informasi umum, misalnya \"mencari informasi HR\" atau \"jam kerja finance\", jangan ubah menjadi contact_employee.
- Jika makna masih sangat ambigu, pilih unknown dengan confidence rendah.

Pesan pengunjung:
{normalized_message}
"""

    parsed = _llm_json(prompt)
    result = _normalize_intent_payload(parsed)
    result = _post_correct_intent(normalized_message, result)
    return result
