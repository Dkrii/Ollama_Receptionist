import re
from typing import Any

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


_CONTACT_MARKER_PATTERNS = (
    r"\bhubungi\b",
    r"\bkontak\b",
    r"\bsambung(?:kan)?\b",
    r"\btelepon\b",
    r"\btelpon\b",
    r"\bcall\b",
    r"\bpanggil\b",
    r"\bketemu\b",
    r"\bbertemu\b",
    r"\btemui\b",
    r"\bjumpa\b",
    r"\bngobrol\b",
    r"\bbicara\b",
    r"\bwhatsapp\b",
    r"\bwa\b",
    r"\btitip pesan\b",
    r"\bpesan buat\b",
    r"\bmau ke\b",
    r"\bingin ke\b",
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


def _text_has_department_prefix(text: str) -> bool:
    normalized = _normalize_message(text)
    return any(re.search(pattern, normalized) for pattern in _DEPARTMENT_CONTEXT_PATTERNS)


def message_may_require_contact_intent(message: str, flow_state: dict | None = None) -> bool:
    normalized = _normalize_message(message)
    if not normalized:
        return False

    if any(re.search(pattern, normalized) for pattern in _CONTACT_MARKER_PATTERNS):
        return True

    if _PERSON_REFERENCE_PATTERN.search(normalized):
        return True

    has_department_context = _text_has_department_prefix(normalized)
    detected_department = extract_department_from_text(normalized)
    if has_department_context and detected_department:
        return True

    if detected_department:
        visit_patterns = (
            r"\bmau\b",
            r"\bingin\b",
            r"\bperlu\b",
            r"\bbutuh\b",
            r"\bcari\b",
            r"\bke\b",
            r"\bkunjung\b",
        )
        if any(re.search(pat, normalized) for pat in visit_patterns):
            return True

    context = flow_state.get("context") if isinstance(flow_state, dict) else {}
    last_topic_type = str((context or {}).get("last_topic_type") or "none").strip().lower()
    if last_topic_type in {"department", "person"} and any(
        re.search(pattern, normalized) for pattern in _CONTACT_REFERENCE_PATTERNS
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
    if detected_dept:
        contact_verbs = (
            r"\bketemu\b",
            r"\bbertemu\b",
            r"\btemui\b",
            r"\bjumpa\b",
            r"\bhubungi\b",
            r"\bkontak\b",
            r"\btelepon\b",
            r"\btelpon\b",
            r"\bcall\b",
            r"\bpanggil\b",
            r"\bsambung\b",
            r"\bbicara\b",
            r"\bmau ke\b",
            r"\bingin ke\b",
        )
        has_contact_verb = any(re.search(pat, normalized) for pat in contact_verbs)
        has_dept_prefix = _text_has_department_prefix(normalized)

        if has_contact_verb or has_dept_prefix:
            result = dict(result)
            result["intent"] = "contact_employee"
            result["target_type"] = "department"
            result["target_value"] = detected_dept
            result["target_department"] = detected_dept
            result["action"] = "contact"
            if result.get("confidence", 0.0) < 0.85:
                result["confidence"] = 0.85
            return result

    if intent == "contact_employee" and action == "ask" and target_type in {"person", "department"}:
        result = dict(result)
        result["action"] = "contact"
        if result.get("confidence", 0.0) < 0.75:
            result["confidence"] = 0.75

    if target_type == "person" and detected_dept:
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

- target_value: nama orang atau divisi yang disebutkan pengunjung (isi jika jelas).
- search_phrase: frasa paling ringkas untuk mencari karyawan — isi jika intent=contact_employee dan target belum eksplisit, kosongkan jika sudah ada di target_value.
- contact_mode: call = minta telepon, notify = minta titip pesan/WA, auto = tidak disebutkan.
- Jika makna masih sangat ambigu, pilih unknown dengan confidence rendah.

Pesan pengunjung:
{normalized_message}
"""

    parsed = _llm_json(prompt)
    result = _normalize_intent_payload(parsed)
    result = _post_correct_intent(normalized_message, result)
    return result
