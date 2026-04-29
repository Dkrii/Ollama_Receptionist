import json
import logging
from typing import Any

from config import settings
from infrastructure.ai_client import generate_text


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
