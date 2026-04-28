import re

from .core import _clamp_confidence, _flow_prompt_context, _llm_json


VISITOR_NAME_FALLBACK = {
    "person_name": "",
    "confidence": 0.0,
}

VISITOR_GOAL_FALLBACK = {
    "visitor_goal": "",
    "confidence": 0.0,
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
  \"person_name\": \"\",
  \"confidence\": 0.0
}}

Aturan:
- person_name hanya berisi nama pengunjung, bukan nama karyawan tujuan.
- Jika pengguna belum menyebut namanya dengan jelas, kembalikan string kosong.
- Jangan sertakan kata seperti \"nama saya\", \"dari\", atau penjelasan tambahan.

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
  \"visitor_goal\": \"\",
  \"confidence\": 0.0
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
