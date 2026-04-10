import re
import json
import logging

import requests

from config import settings


SOCIAL_PHRASES = (
    "halo",
    "hai",
    "hi",
    "hello",
    "selamat pagi",
    "selamat siang",
    "selamat sore",
    "selamat malam",
    "pagi",
    "siang",
    "sore",
    "malam",
    "apa kabar",
    "terima kasih",
    "makasih",
    "thanks",
    "thank you",
    "dadah",
    "daah",
    "bye",
    "good bye",
    "sampai jumpa",
)

SOCIAL_TOKENS = {
    "halo",
    "hallo",
    "hai",
    "hi",
    "hello",
    "pagi",
    "siang",
    "sore",
    "malam",
    "thanks",
    "bye",
}

INTENT_FALLBACK = {
    "intent": "unknown",
    "confidence": 0.0,
    "target_type": "none",
    "target_value": "",
    "action": "none",
}

CONTACT_SEMANTIC_HINTS = (
    "mau ngobrol",
    "ingin ngobrol",
    "bisa ngobrol",
    "mau bicara",
    "ingin bicara",
    "ketemu",
    "bertemu",
    "temui",
    "menemui",
    "jumpa",
    "saya butuh orang",
    "bisa sambung",
)

REFERENCE_TOPICS = (
    "orangnya",
    "orang itu",
    "timnya",
    "tim itu",
    "mereka",
    "yang ngurus",
    "yang urus",
)

DEPARTMENT_ALIASES = {
    "it": "IT",
    "ti": "IT",
    "teknologi informasi": "IT",
    "informatika": "IT",
    "sistem": "IT",
    "komputer": "IT",
    "teknis": "IT",
    "hr": "HR",
    "hrd": "HR",
    "human resource": "HR",
    "human resources": "HR",
}

_logger = logging.getLogger(__name__)
_http_session = requests.Session()


def _normalize_message(message: str) -> str:
    return " ".join((message or "").lower().split())


def _message_tokens(message: str) -> list[str]:
    normalized = _normalize_message(message)
    cleaned = re.sub(r"[^a-z0-9\s]", " ", normalized)
    return [token for token in cleaned.split() if token]


def is_social_message(message: str) -> bool:
    normalized = _normalize_message(message)
    if not normalized:
        return False

    if any(phrase in normalized for phrase in SOCIAL_PHRASES):
        return True

    tokens = _message_tokens(normalized)
    if not tokens:
        return False

    if len(tokens) <= 3 and all(token in SOCIAL_TOKENS for token in tokens):
        return True

    return False


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


def _normalize_classification(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return dict(INTENT_FALLBACK)

    intent = str(payload.get("intent") or "unknown").strip().lower()
    if intent not in {"company_info", "contact_employee", "confirm_yes", "confirm_no", "small_talk", "unknown"}:
        intent = "unknown"

    target_type = str(payload.get("target_type") or "none").strip().lower()
    if target_type not in {"department", "person", "none"}:
        target_type = "none"

    target_value = str(payload.get("target_value") or "").strip()
    if target_type == "none":
        target_value = ""

    action = str(payload.get("action") or "none").strip().lower()
    if action not in {"ask", "contact", "confirm", "none"}:
        action = "none"

    raw_confidence = payload.get("confidence", 0.0)
    try:
        confidence = float(raw_confidence)
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return {
        "intent": intent,
        "confidence": confidence,
        "target_type": target_type,
        "target_value": target_value,
        "action": action,
    }


def _canonical_department(value: str) -> str:
    normalized = _normalize_message(value)
    if not normalized:
        return ""

    for alias, canonical in DEPARTMENT_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", normalized):
            return canonical

    compact = normalized.replace(" ", "")
    if compact in {"it", "hr", "hrd"}:
        return compact.upper() if compact != "hrd" else "HR"

    return value.strip()


def _infer_department_from_text(message: str) -> str:
    normalized = _normalize_message(message)
    if not normalized:
        return ""

    for alias, canonical in DEPARTMENT_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", normalized):
            return canonical
    return ""


def _heuristic_intent(message: str, flow_state: dict | None = None) -> dict:
    normalized = _normalize_message(message)
    if not normalized:
        return dict(INTENT_FALLBACK)

    tokens = set(_message_tokens(normalized))

    short_confirmation_candidate = len(tokens) <= 4 and not normalized.endswith("?")

    if short_confirmation_candidate and {"iya", "ya", "yes", "oke", "ok", "boleh", "lanjut"}.intersection(tokens):
        return {
            "intent": "confirm_yes",
            "confidence": 0.86,
            "target_type": "none",
            "target_value": "",
            "action": "confirm",
        }
    if short_confirmation_candidate and {"tidak", "nggak", "ga", "gak", "no", "batal"}.intersection(tokens):
        return {
            "intent": "confirm_no",
            "confidence": 0.86,
            "target_type": "none",
            "target_value": "",
            "action": "confirm",
        }

    inferred_department = _infer_department_from_text(normalized)
    has_contact_semantic = any(phrase in normalized for phrase in CONTACT_SEMANTIC_HINTS)
    has_reference_topic = any(phrase in normalized for phrase in REFERENCE_TOPICS)
    has_obvious_contact_verb = any(
        marker in normalized
        for marker in ("hubungi", "kontak", "sambungkan", "telepon", "telpon", "call", "panggil")
    )

    if has_contact_semantic or has_obvious_contact_verb:
        target_type = "department" if inferred_department else "none"
        target_value = inferred_department if inferred_department else ""
        return {
            "intent": "contact_employee",
            "confidence": 0.78 if has_contact_semantic else 0.83,
            "target_type": target_type,
            "target_value": target_value,
            "action": "contact",
        }

    if inferred_department:
        return {
            "intent": "company_info",
            "confidence": 0.75,
            "target_type": "department",
            "target_value": inferred_department,
            "action": "ask",
        }

    flow_context = flow_state.get("context") if isinstance(flow_state, dict) else {}
    last_topic_value = str((flow_context or {}).get("last_topic_value") or "").strip()
    last_topic_type = str((flow_context or {}).get("last_topic_type") or "").strip().lower()
    if has_reference_topic and last_topic_value and last_topic_type == "department":
        return {
            "intent": "contact_employee",
            "confidence": 0.71,
            "target_type": "department",
            "target_value": _canonical_department(last_topic_value),
            "action": "contact",
        }

    return dict(INTENT_FALLBACK)


def _llm_intent(message: str, flow_state: dict | None = None) -> dict:
    context = flow_state.get("context") if isinstance(flow_state, dict) else {}
    last_topic_type = str((context or {}).get("last_topic_type") or "none")
    last_topic_value = str((context or {}).get("last_topic_value") or "")

    prompt = f"""Tugas: klasifikasikan satu pesan pengguna untuk resepsionis perusahaan.

KONTEKS:
- last_topic_type: {last_topic_type}
- last_topic_value: {last_topic_value or '-'}

Balas HANYA JSON valid (tanpa markdown, tanpa teks tambahan) dengan schema:
{{
  "intent": "company_info|contact_employee|confirm_yes|confirm_no|small_talk|unknown",
  "confidence": 0.0,
  "target_type": "department|person|none",
  "target_value": "",
  "action": "ask|contact|confirm|none"
}}

Aturan:
- Fokus pada MAKNA, bukan keyword literal.
- "mau ngobrol", "ketemu", "orang yang ngurus" bisa berarti contact_employee.
- Jika ada rujukan seperti "orangnya", gunakan konteks last_topic bila relevan.
- Jika ambigu berat, pilih unknown dengan confidence rendah.
- Jangan sertakan penjelasan, alasan, atau teks selain JSON.

Pesan pengguna:
{message}
"""

    max_retries = max(1, int(getattr(settings, "chat_intent_max_retries", 2)))
    last_raw_response = ""

    for attempt in range(1, max_retries + 1):
        try:
            response = _http_session.post(
                f"{settings.ollama_base_url}/api/generate",
                json={
                    "model": settings.ollama_chat_model,
                    "prompt": prompt,
                    "stream": False,
                    "keep_alive": "20m",
                    "options": {
                        "temperature": 0.0,
                        "num_predict": min(180, settings.ollama_num_predict_short + 60),
                        "num_ctx": settings.ollama_num_ctx,
                    },
                },
                timeout=60,
            )
            response.raise_for_status()
            last_raw_response = str((response.json() or {}).get("response", "") or "")
            parsed = _extract_json_object(last_raw_response)
            if not isinstance(parsed, dict):
                continue

            normalized = _normalize_classification(parsed)
            if normalized["target_type"] == "department" and normalized["target_value"]:
                normalized["target_value"] = _canonical_department(normalized["target_value"])
            return normalized
        except Exception:
            _logger.exception("chat.intent llm classification failed attempt=%s", attempt)

    if last_raw_response.strip():
        parsed = _extract_json_object(last_raw_response)
        normalized = _normalize_classification(parsed)
        if normalized["target_type"] == "department" and normalized["target_value"]:
            normalized["target_value"] = _canonical_department(normalized["target_value"])
        return normalized

    return dict(INTENT_FALLBACK)


def detect_conversation_intent(message: str, flow_state: dict | None = None, allow_llm: bool = True) -> dict:
    heuristic = _heuristic_intent(message, flow_state=flow_state)
    if heuristic["intent"] in {"contact_employee", "company_info", "confirm_yes", "confirm_no"} and heuristic["confidence"] >= 0.7:
        return heuristic

    if heuristic["confidence"] >= 0.82:
        return heuristic

    if not allow_llm:
        return heuristic

    llm_result = _llm_intent(message, flow_state=flow_state)
    if llm_result["confidence"] >= 0.7 and llm_result["intent"] in {"contact_employee", "company_info", "confirm_yes", "confirm_no"}:
        return llm_result

    if heuristic["confidence"] > llm_result["confidence"]:
        return heuristic
    return llm_result
