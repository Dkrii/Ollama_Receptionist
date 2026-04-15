import json
import logging
import re
from typing import Any

from ai_client import generate_text
from api.chat.department import KNOWN_DEPARTMENTS, extract_department_from_text, normalize_department
from config import settings


INTENT_FALLBACK = {
    "intent": "unknown",
    "confidence": 0.0,
    "target_type": "none",
    "target_value": "",
    "target_department": "",
    "action": "none",
    "contact_mode": "auto",
}

SEARCH_FALLBACK = {
    "search_phrase": "",
    "confidence": 0.0,
}

VISITOR_NAME_FALLBACK = {
    "person_name": "",
    "confidence": 0.0,
}

VISITOR_GOAL_FALLBACK = {
    "visitor_goal": "",
    "confidence": 0.0,
}

UNAVAILABLE_CHOICE_FALLBACK = {
    "decision": "unknown",
    "confidence": 0.0,
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



_logger = logging.getLogger(__name__)


def _normalize_message(message: str) -> str:
    return " ".join((message or "").lower().split())


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

    candidate = content[start_idx : end_idx + 1]
    try:
        parsed = json.loads(candidate)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _clamp_confidence(raw_value: Any) -> float:
    try:
        confidence = float(raw_value)
    except Exception:
        confidence = 0.0
    return max(0.0, min(1.0, confidence))




def _normalize_contact_mode(value: str | None) -> str:
    mode = str(value or "auto").strip().lower()
    if mode in {"call", "notify", "auto"}:
        return mode
    return "auto"


def _text_contains_department(text: str) -> bool:
    """Cek apakah teks menyebut nama departemen yang dikenal."""
    return extract_department_from_text(text) is not None


def _text_has_department_prefix(text: str) -> bool:
    """Cek apakah ada pola 'tim X', 'divisi X', 'bagian X' di teks."""
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

    # Deteksi frasa departemen yang kuat: "tim HR", "divisi IT",
    # "bagian Finance", "ke HR", dsb. — terlepas dari verb eksplisit.
    has_department_context = _text_has_department_prefix(normalized)
    detected_department = extract_department_from_text(normalized)

    if has_department_context and detected_department:
        return True

    # Bahkan tanpa prefix "tim/divisi", jika ada departemen dikenal + kata kunjungan
    if detected_department:
        visit_patterns = (
            r"\bmau\b", r"\bingin\b", r"\bperlu\b", r"\bbutuh\b",
            r"\bcari\b", r"\bke\b", r"\bkunjung\b",
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


def _flow_prompt_context(flow_state: dict | None) -> dict[str, str]:
    context = flow_state.get("context") if isinstance(flow_state, dict) else {}
    selected = flow_state.get("selected") if isinstance(flow_state, dict) else {}

    return {
        "stage": str((flow_state or {}).get("stage") or "idle").strip().lower(),
        "last_topic_type": str((context or {}).get("last_topic_type") or "none").strip().lower(),
        "last_topic_value": str((context or {}).get("last_topic_value") or "").strip(),
        "last_intent": str((context or {}).get("last_intent") or "unknown").strip().lower(),
        "selected_name": str((selected or {}).get("nama") or "").strip(),
        "selected_department": str((selected or {}).get("departemen") or "").strip(),
        "selected_position": str((selected or {}).get("jabatan") or "").strip(),
        "saved_action": str((flow_state or {}).get("action") or "").strip().lower(),
    }


def _llm_json(prompt: str) -> dict | None:
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
                max_tokens=min(220, settings.ollama_num_predict_short + 80),
                timeout=timeout_seconds,
            )
            last_raw_response = str((payload or {}).get("response", "") or "")
            parsed = _extract_json_object(last_raw_response)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            _logger.exception("chat.intent llm failed attempt=%s", attempt)

    if last_raw_response.strip():
        return _extract_json_object(last_raw_response)
    return None


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
        # Cek apakah LLM salah mengklasifikasikan departemen sebagai person
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

    # search_phrase diekstrak langsung dari prompt intent (tanpa LLM call terpisah)
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
    """
    Post-correction layer: perbaiki kesalahan umum LLM sebelum dikembalikan.

    Fokus utama:
    - Frasa 'tim HR', 'divisi IT', 'bagian Finance' HARUS selalu menjadi
      target_type=department + action=contact.
    - 'ingin ketemu/mau ketemu + departemen' = contact, bukan ask.
    """
    normalized = _normalize_message(message)
    target_type = result.get("target_type", "none")
    action = result.get("action", "none")
    intent = result.get("intent", "unknown")

    detected_dept = extract_department_from_text(normalized)

    # Rule 1: Jika ada departemen terdeteksi + ada kata kunjungan/kontak,
    # paksa menjadi contact_employee + department + contact
    if detected_dept:
        contact_verbs = (
            r"\bketemu\b", r"\bbertemu\b", r"\btemui\b", r"\bjumpa\b",
            r"\bhubungi\b", r"\bkontak\b", r"\btelepon\b", r"\btelpon\b",
            r"\bcall\b", r"\bpanggil\b", r"\bsambung\b", r"\bbicara\b",
            r"\bmau ke\b", r"\bingin ke\b",
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
            if result["confidence"] < 0.85:
                result["confidence"] = 0.85
            return result

    # Rule 2: Jika intent=contact_employee tapi action=ask + ada target,
    # koreksi action menjadi contact (karena 'ingin' = niat, bukan hanya bertanya)
    if intent == "contact_employee" and action == "ask" and target_type in {"person", "department"}:
        result = dict(result)
        result["action"] = "contact"
        if result["confidence"] < 0.75:
            result["confidence"] = 0.75

    if target_type == "person" and detected_dept:
        result = dict(result)
        result["target_department"] = detected_dept

    return result


def _normalize_search_payload(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return dict(SEARCH_FALLBACK)

    search_phrase = str(payload.get("search_phrase") or "").strip()
    canonical = normalize_department(search_phrase)
    if canonical:
        search_phrase = canonical

    return {
        "search_phrase": search_phrase,
        "confidence": _clamp_confidence(payload.get("confidence", 0.0)),
    }


def _normalize_unavailable_choice_payload(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return dict(UNAVAILABLE_CHOICE_FALLBACK)

    decision = str(payload.get("decision") or "unknown").strip().lower()
    if decision not in {"leave_message", "wait_in_lobby", "decline", "unknown"}:
        decision = "unknown"

    return {
        "decision": decision,
        "confidence": _clamp_confidence(payload.get("confidence", 0.0)),
    }


def _normalize_visitor_name_payload(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return dict(VISITOR_NAME_FALLBACK)

    person_name = re.sub(r"\s+", " ", str(payload.get("person_name") or "").strip())
    return {
        "person_name": person_name,
        "confidence": _clamp_confidence(payload.get("confidence", 0.0)),
    }


def _normalize_visitor_goal_payload(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return dict(VISITOR_GOAL_FALLBACK)

    visitor_goal = re.sub(r"\s+", " ", str(payload.get("visitor_goal") or "").strip())
    return {
        "visitor_goal": visitor_goal,
        "confidence": _clamp_confidence(payload.get("confidence", 0.0)),
    }


def detect_conversation_intent(message: str, flow_state: dict | None = None, allow_llm: bool = True) -> dict:
    """
    Klasifikasikan intent percakapan dan sekaligus ekstrak search_phrase dalam satu LLM call.

    Field tambahan `search_phrase` diisi LLM ketika target kontak tidak eksplisit,
    sehingga tidak perlu call terpisah ke extract_contact_search_phrase().
    """
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
  "intent": "company_info|contact_employee|confirm_yes|confirm_no|small_talk|unknown",
  "confidence": 0.0,
  "target_type": "department|person|none",
  "target_value": "",
  "target_department": "",
  "action": "ask|contact|confirm|none",
  "contact_mode": "call|notify|auto",
  "search_phrase": ""
}}

Panduan pengisian:
- Pahami MAKSUD pengunjung secara keseluruhan, bukan cari kata tertentu.
- contact_employee: pengunjung ingin bertemu, dihubungkan, atau menitipkan sesuatu kepada seseorang atau tim/divisi.
- company_info: pengunjung ingin tahu informasi perusahaan, jam kerja, fasilitas, profil, dll.
- confirm_yes / confirm_no: jawaban atas pertanyaan konfirmasi yang sedang aktif.
- small_talk: sapaan, terima kasih, pertanyaan umum di luar topik di atas.

ATURAN PENTING target_type:
- Jika pengunjung menyebut nama DIVISI/TIM/DEPARTEMEN (contoh: "tim HR", "divisi IT", "bagian Finance", "ke IT", "Human Capital", "HRD"), maka target_type HARUS "department" dan action HARUS "contact".
- Jika pengunjung menyebut nama ORANG (contoh: "Pak Budi", "Bu Sari"), maka target_type = "person".
- Jika pengunjung menyebut nama orang sekaligus divisi/departemennya (contoh: "Budi dari IT"), isi target_value dengan nama orangnya dan target_department dengan divisinya.
- Kalimat seperti "Saya mau ketemu tim HR" atau "Saya ingin ke bagian IT" = contact_employee, target_type=department, action=contact.

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


def extract_contact_search_phrase(message: str, flow_state: dict | None = None) -> str:
    normalized_message = (message or "").strip()
    if not normalized_message:
        return ""

    flow_context = _flow_prompt_context(flow_state)
    prompt = f"""Tugas: ekstrak target kontak utama dari pesan pengguna.

KONTEKS:
- last_topic_type: {flow_context['last_topic_type']}
- last_topic_value: {flow_context['last_topic_value'] or '-'}
- selected_name: {flow_context['selected_name'] or '-'}
- selected_department: {flow_context['selected_department'] or '-'}

Balas HANYA JSON valid:
{{
  "search_phrase": "",
  "confidence": 0.0
}}

Aturan:
- search_phrase harus berisi hanya nama orang atau nama divisi yang paling relevan.
- Jangan sertakan kata kerja, filler, atau frasa sopan santun.
- Jika pengguna merujuk konteks sebelumnya, gunakan referensi itu.
- Jika tidak ada target yang jelas, kembalikan string kosong.

Pesan pengguna:
{normalized_message}
"""

    parsed = _llm_json(prompt)
    normalized = _normalize_search_payload(parsed)
    return normalized["search_phrase"]


def extract_visitor_name(message: str, flow_state: dict | None = None) -> str:
    normalized_message = (message or "").strip()
    if not normalized_message:
        return ""

    flow_context = _flow_prompt_context(flow_state)
    prompt = f"""Tugas: ekstrak nama pengunjung dari pesan pengguna.

KONTEKS:
- stage: {flow_context['stage']}
- selected_name: {flow_context['selected_name'] or '-'}
- selected_department: {flow_context['selected_department'] or '-'}

Balas HANYA JSON valid:
{{
  "person_name": "",
  "confidence": 0.0
}}

Aturan:
- person_name hanya berisi nama pengunjung, bukan nama karyawan tujuan.
- Jika pengguna belum menyebut namanya dengan jelas, kembalikan string kosong.
- Jangan sertakan kata seperti "nama saya", "dari", atau penjelasan tambahan.

Pesan pengguna:
{normalized_message}
"""

    parsed = _llm_json(prompt)
    normalized = _normalize_visitor_name_payload(parsed)
    return normalized["person_name"]


def extract_visitor_goal(message: str, flow_state: dict | None = None) -> str:
    normalized_message = (message or "").strip()
    if not normalized_message:
        return ""

    flow_context = _flow_prompt_context(flow_state)
    prompt = f"""Tugas: ekstrak tujuan atau keperluan kunjungan dari pesan pengguna.

KONTEKS:
- stage: {flow_context['stage']}
- selected_name: {flow_context['selected_name'] or '-'}
- selected_department: {flow_context['selected_department'] or '-'}

Balas HANYA JSON valid:
{{
  "visitor_goal": "",
  "confidence": 0.0
}}

Aturan:
- visitor_goal harus ringkas, satu frasa singkat yang mewakili tujuan kunjungan.
- Jangan sertakan nama pengunjung kecuali memang bagian inti dari tujuan.
- Jika tujuan belum jelas, kembalikan string kosong.

Pesan pengguna:
{normalized_message}
"""

    parsed = _llm_json(prompt)
    normalized = _normalize_visitor_goal_payload(parsed)
    return normalized["visitor_goal"]


def interpret_unavailable_choice(message: str, flow_state: dict | None = None) -> dict:
    normalized_message = (message or "").strip()
    if not normalized_message:
        return dict(UNAVAILABLE_CHOICE_FALLBACK)

    flow_context = _flow_prompt_context(flow_state)
    prompt = f"""Tugas: klasifikasikan keputusan pengguna setelah diberi tahu bahwa target sedang tidak tersedia.

KONTEKS:
- selected_name: {flow_context['selected_name'] or '-'}
- selected_department: {flow_context['selected_department'] or '-'}
- stage: {flow_context['stage']}

Balas HANYA JSON valid:
{{
  "decision": "leave_message|wait_in_lobby|decline|unknown",
  "confidence": 0.0
}}

Aturan:
- leave_message jika pengguna setuju menitipkan pesan.
- wait_in_lobby jika pengguna memilih menunggu di lobby/front office.
- decline jika pengguna menolak, membatalkan, atau tidak ingin lanjut.
- unknown jika keputusan belum jelas.

Pesan pengguna:
{normalized_message}
"""

    parsed = _llm_json(prompt)
    return _normalize_unavailable_choice_payload(parsed)
