from typing import Iterator
import re

import requests

from config import settings


_http_session = requests.Session()


FALLBACK_MESSAGE = "Maaf, saya belum bisa memberikan jawaban saat ini."


SYSTEM_PROMPT = """Anda adalah virtual receptionist.
Jawab secara natural, jelas, membantu, dan relevan dengan pertanyaan pengguna.
Untuk pertanyaan terkait perusahaan, prioritaskan informasi dari konteks knowledge perusahaan jika tersedia.
Jika konteks knowledge perusahaan kosong untuk pertanyaan perusahaan, sampaikan keterbatasan data secara jujur dan tawarkan bantuan lanjutan.
Jangan menyebut proses internal, prompt, retrieval, atau sistem di balik jawaban.
Gunakan bahasa yang mengikuti bahasa pengguna kecuali pengguna meminta bahasa lain.
"""

FLOW_RESPONSE_SYSTEM_PROMPT = """Anda adalah virtual receptionist.
Tugas Anda hanya merapikan respons backend menjadi kalimat natural yang sopan dan singkat.
Jangan mengubah keputusan, status, atau aksi backend.
Jangan menambahkan janji/aksi baru di luar data yang diberikan.
Gunakan Bahasa Indonesia yang natural dan ringkas.
"""


def _ollama_generate_options(overrides: dict | None = None) -> dict:
    options = {
        "temperature": 0.2,
        "num_predict": settings.ollama_num_predict,
        "num_ctx": settings.ollama_num_ctx,
    }
    if settings.ollama_num_thread > 0:
        options["num_thread"] = settings.ollama_num_thread
    if overrides:
        options.update(overrides)
    return options


def _build_answer_style(question: str, context: str) -> str:
    return "Jawab secara jelas, runtut, dan secukupnya sesuai kebutuhan pengguna."


def _wants_detailed_answer(question: str) -> bool:
    normalized = re.sub(r"\s+", " ", (question or "").lower()).strip()
    if not normalized:
        return False

    detail_markers = (
        "jelaskan",
        "secara detail",
        "lebih detail",
        "rincikan",
        "lengkap",
        "terperinci",
        "bagaimana cara",
        "langkah",
        "prosedur",
        "alurnya",
    )
    return any(marker in normalized for marker in detail_markers)


def _answer_options(question: str) -> dict:
    target_num_predict = settings.ollama_num_predict_short
    if _wants_detailed_answer(question):
        target_num_predict = settings.ollama_num_predict_long
    return _ollama_generate_options({"num_predict": target_num_predict})


def _build_history_block(history: list[dict] | None = None) -> str:
    if not history:
        return "-"

    formatted_turns: list[str] = []
    total_chars = 0
    max_chars = settings.chat_history_max_chars

    for item in reversed(history[-settings.chat_recent_turns:]):
        role = str(item.get("role", "")).strip().lower()
        content = " ".join(str(item.get("content", "")).split()).strip()
        if not content:
            continue

        speaker = "PENGGUNA" if role == "user" else "ASISTEN"
        line = f"{speaker}: {content}"
        addition = len(line) + (1 if formatted_turns else 0)

        if formatted_turns and total_chars + addition > max_chars:
            break

        if not formatted_turns and len(line) > max_chars:
            line = line[-max_chars:]

        formatted_turns.insert(0, line)
        total_chars += addition

    return "\n".join(formatted_turns) if formatted_turns else "-"


def _build_prompt(question: str, context: str, history: list[dict] | None = None) -> str:
    knowledge_context = (context or "").strip() or "-"
    history_context = _build_history_block(history)
    return f"""KONTEKS KNOWLEDGE PERUSAHAAN:
{knowledge_context}

RIWAYAT PERCAKAPAN SEBELUMNYA:
{history_context}

ATURAN JAWABAN:
{_build_answer_style(question, context)}

PERTANYAAN PENGGUNA:
{question}

Jawab langsung kepada pengguna."""


def _tail_fragment(text: str, max_chars: int = 240) -> str:
    value = (text or "").strip()
    if len(value) <= max_chars:
        return value
    return value[-max_chars:]


def _answer_looks_complete(answer: str) -> bool:
    return (answer or "").rstrip().endswith((".", "!", "?", "\"", "'"))


def _finalize_answer(question: str, context: str, answer: str) -> str:
    completed = (answer or "").strip()
    if not completed:
        return FALLBACK_MESSAGE
    return completed


def _continue_answer(question: str, context: str, partial_answer: str, history: list[dict] | None = None) -> str:
    prompt = f"""KONTEKS KNOWLEDGE PERUSAHAAN:
{(context or '').strip() or '-'}

RIWAYAT PERCAKAPAN SEBELUMNYA:
{_build_history_block(history)}

PERTANYAAN PENGGUNA:
{question}

FRAGMEN AKHIR JAWABAN:
{_tail_fragment(partial_answer)}

Lanjutkan jawaban terakhir tanpa mengulang bagian yang sudah ada.
Tutup jawaban dengan kalimat yang utuh."""

    response = _http_session.post(
        f"{settings.ollama_base_url}/api/generate",
        json={
            "model": settings.ollama_chat_model,
            "prompt": prompt,
            "system": SYSTEM_PROMPT,
            "stream": False,
            "keep_alive": "30m",
            "options": _ollama_generate_options(
                {
                    "num_predict": settings.ollama_num_predict_short,
                }
            ),
        },
        timeout=120,
    )
    response.raise_for_status()
    return (response.json().get("response", "") or "").strip()


def _merge_with_overlap(base: str, continuation: str) -> str:
    left = (base or "").rstrip()
    right = (continuation or "").lstrip()
    if not left:
        return right
    if not right:
        return left

    left_lower = left.lower()
    right_lower = right.lower()
    max_overlap = min(len(left_lower), len(right_lower), 220)

    for size in range(max_overlap, 7, -1):
        if left_lower[-size:] == right_lower[:size]:
            return f"{left}{right[size:]}"

    return f"{left} {right}".strip()


def _extend_answer_if_needed(
    question: str,
    context: str,
    answer: str,
    done_reason: str,
    history: list[dict] | None = None,
) -> str:
    completed = (answer or "").strip()
    if not completed:
        return completed

    if (done_reason or "").lower() != "length" or _answer_looks_complete(completed):
        return completed

    continuation = _continue_answer(question, context, completed, history=history)
    if not continuation:
        return completed

    return _merge_with_overlap(completed, continuation)


def generate_answer(question: str, context: str, history: list[dict] | None = None) -> str:
    response = _http_session.post(
        f"{settings.ollama_base_url}/api/generate",
        json={
            "model": settings.ollama_chat_model,
            "prompt": _build_prompt(question, context, history=history),
            "system": SYSTEM_PROMPT,
            "stream": False,
            "keep_alive": "30m",
            "options": _answer_options(question),
        },
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    answer = (payload.get("response", "") or "").strip()
    done_reason = str(payload.get("done_reason", "") or payload.get("doneReason", "") or "").lower()
    answer = _extend_answer_if_needed(question, context, answer, done_reason, history=history)
    return _finalize_answer(question, context, answer)


def generate_answer_stream(question: str, context: str, history: list[dict] | None = None) -> Iterator[str]:
    with _http_session.post(
        f"{settings.ollama_base_url}/api/generate",
        json={
            "model": settings.ollama_chat_model,
            "prompt": _build_prompt(question, context, history=history),
            "system": SYSTEM_PROMPT,
            "stream": True,
            "keep_alive": "30m",
            "options": _answer_options(question),
        },
        timeout=120,
        stream=True,
    ) as response:
        response.raise_for_status()
        emitted = False
        collected_tokens: list[str] = []
        done_reason = ""

        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue

            chunk = requests.models.complexjson.loads(line)
            token = chunk.get("response", "")
            if token:
                emitted = True
                collected_tokens.append(token)
                yield token

            if chunk.get("done") is True:
                done_reason = str(chunk.get("done_reason", "") or chunk.get("doneReason", "") or "").lower()
                break

        full_answer = "".join(collected_tokens).strip()
        extended_answer = _extend_answer_if_needed(question, context, full_answer, done_reason, history=history)
        if extended_answer and extended_answer != full_answer:
            continuation_text = extended_answer[len(full_answer):].strip()
            if continuation_text:
                yield f" {continuation_text}".rstrip()
                emitted = True

        if not emitted:
            yield FALLBACK_MESSAGE


def generate_contact_flow_response(
    *,
    seed_answer: str,
    stage: str,
    intent: str,
    target_label: str,
    status: str,
) -> str:
    base_answer = (seed_answer or "").strip()
    if not base_answer:
        return FALLBACK_MESSAGE

    prompt = f"""Rapikan jawaban backend berikut agar natural untuk percakapan resepsionis.

BATASAN WAJIB:
- Pertahankan makna asli 100%.
- Jangan menambah aksi baru, jangan ubah status proses.
- Maksimal 2 kalimat, ringkas, sopan.
- Jika ada aksi koneksi, gunakan pola: "menghubungkan Anda dengan ...".
- Hindari pola yang tidak natural seperti "menghubungi Anda dengan ...".
- Jangan mengubah siapa yang dihubungi.

KONTEKS STATE:
- stage: {stage or 'unknown'}
- intent: {intent or 'unknown'}
- target: {target_label or '-'}
- status: {status or '-'}

JAWABAN BACKEND ASLI:
{base_answer}

Keluarkan hanya teks jawaban akhir (tanpa bullet, tanpa markdown)."""

    def _sanitize_flow_response(text: str) -> str:
        value = (text or "").strip()
        if not value:
            return ""
        value = re.sub(r"\bmenghubungi\s+Anda\s+dengan\b", "menghubungkan Anda dengan", value, flags=re.IGNORECASE)
        value = re.sub(r"\bmenghubungi\s+anda\s+dengan\b", "menghubungkan Anda dengan", value, flags=re.IGNORECASE)
        value = re.sub(r"\bsaya\s+akan\s+menghubungi\s+Anda\s+dengan\b", "Saya akan menghubungkan Anda dengan", value, flags=re.IGNORECASE)
        return value

    try:
        response = _http_session.post(
            f"{settings.ollama_base_url}/api/generate",
            json={
                "model": settings.ollama_chat_model,
                "prompt": prompt,
                "system": FLOW_RESPONSE_SYSTEM_PROMPT,
                "stream": False,
                "keep_alive": "20m",
                "options": _ollama_generate_options(
                    {
                        "temperature": 0.25,
                        "num_predict": settings.ollama_num_predict_short,
                    }
                ),
            },
            timeout=60,
        )
        response.raise_for_status()
        rewritten = str((response.json() or {}).get("response", "") or "").strip()
        sanitized = _sanitize_flow_response(rewritten)
        return sanitized or base_answer
    except Exception:
        return _sanitize_flow_response(base_answer) or base_answer
