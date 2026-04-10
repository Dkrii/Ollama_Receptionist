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


# =========================
# OPTIONS
# =========================

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


def _answer_options() -> dict:
    return _ollama_generate_options({
        "num_predict": settings.ollama_num_predict
    })


# =========================
# HISTORY
# =========================

def _build_history_block(history: list[dict] | None = None) -> str:
    if not history:
        return "-"

    formatted = []
    total_chars = 0
    max_chars = settings.chat_history_max_chars

    for item in reversed(history[-settings.chat_recent_turns:]):
        role = item.get("role", "").lower()
        content = " ".join(str(item.get("content", "")).split()).strip()
        if not content:
            continue

        speaker = "PENGGUNA" if role == "user" else "ASISTEN"
        line = f"{speaker}: {content}"

        if total_chars + len(line) > max_chars:
            break

        formatted.insert(0, line)
        total_chars += len(line)

    return "\n".join(formatted) if formatted else "-"


# =========================
# PROMPT
# =========================

def _build_prompt(question: str, context: str, history=None) -> str:
    return f"""KONTEKS KNOWLEDGE PERUSAHAAN:
{(context or "").strip() or "-"}

RIWAYAT PERCAKAPAN:
{_build_history_block(history)}

PERTANYAAN:
{question}

Jawab secara jelas, ringkas, dan langsung ke inti."""


# =========================
# DETECTION
# =========================

def _answer_looks_complete(answer: str) -> bool:
    text = (answer or "").strip()

    if not text:
        return False

    if not text.endswith((".", "!", "?")):
        return False

    dangling = ("dan", "atau", "serta", "adalah", "merupakan")
    words = text.lower().split()
    last_words = words[-3:] if len(words) >= 3 else words

    if any(w in dangling for w in last_words):
        return False

    return True


def _tail_fragment(text: str, max_chars: int = 240) -> str:
    return text[-max_chars:] if len(text) > max_chars else text


# =========================
# CONTINUE
# =========================

def _continue_answer(question, context, partial, history=None):
    prompt = f"""KONTEKS:
{(context or "-")}

PERTANYAAN:
{question}

FRAGMEN:
{_tail_fragment(partial)}

Lanjutkan jawaban tanpa mengulang.
Selesaikan bagian yang terpotong.
Akhiri dengan kalimat lengkap."""

    response = _http_session.post(
        f"{settings.ollama_base_url}/api/generate",
        json={
            "model": settings.ollama_chat_model,
            "prompt": prompt,
            "system": SYSTEM_PROMPT,
            "stream": False,
            "options": _ollama_generate_options({
                "num_predict": settings.ollama_num_predict_long
            }),
        },
        timeout=120,
    )

    response.raise_for_status()
    return (response.json().get("response", "") or "").strip()


def _merge_with_overlap(base: str, continuation: str) -> str:
    left = base.rstrip()
    right = continuation.lstrip()

    left_lower = left.lower()
    right_lower = right.lower()

    for i in range(min(len(left), len(right), 200), 5, -1):
        if left_lower[-i:] == right_lower[:i]:
            return left + right[i:]

    return f"{left} {right}"


def _extend_answer_if_needed(question, context, answer, done_reason, history=None):
    current = (answer or "").strip()
    if not current:
        return current

    max_retry = 1

    for _ in range(max_retry):
        is_cutoff = done_reason == "length"
        complete = _answer_looks_complete(current)

        if not is_cutoff and complete:
            break

        continuation = _continue_answer(question, context, current, history)

        if not continuation:
            break

        current = _merge_with_overlap(current, continuation)

    return current


# =========================
# SUMMARIZE
# =========================

def _should_summarize(question: str) -> bool:
    q = (question or "").lower()
    markers = ("jelaskan", "detail", "rincikan", "lengkap")
    return not any(m in q for m in markers)


def _summarize_answer(answer: str) -> str:
    text = (answer or "").strip()

    if len(text) < 220:
        return text

    prompt = f"""Ringkas jawaban berikut menjadi inti:

- Maksimal 2 kalimat
- Ambil poin paling penting saja
- Jangan bertele-tele

{text}
"""

    try:
        response = _http_session.post(
            f"{settings.ollama_base_url}/api/generate",
            json={
                "model": settings.ollama_chat_model,
                "prompt": prompt,
                "system": SYSTEM_PROMPT,
                "stream": False,
                "options": _ollama_generate_options({
                    "num_predict": settings.ollama_num_predict_short
                }),
            },
            timeout=60,
        )

        response.raise_for_status()
        short = (response.json().get("response", "") or "").strip()

        return short if short else text

    except Exception:
        return text


# =========================
# FINAL
# =========================

def _finalize(answer: str) -> str:
    return answer.strip() if answer else FALLBACK_MESSAGE


# =========================
# MAIN
# =========================

def generate_answer(question: str, context: str, history=None) -> str:
    response = _http_session.post(
        f"{settings.ollama_base_url}/api/generate",
        json={
            "model": settings.ollama_chat_model,
            "prompt": _build_prompt(question, context, history),
            "system": SYSTEM_PROMPT,
            "stream": False,
            "options": _answer_options(),
        },
        timeout=120,
    )

    response.raise_for_status()
    payload = response.json()

    answer = (payload.get("response", "") or "").strip()
    done_reason = (payload.get("done_reason", "") or "").lower()

    answer = _extend_answer_if_needed(
        question, context, answer, done_reason, history
    )

    if _should_summarize(question):
        answer = _summarize_answer(answer)

    return _finalize(answer)


# =========================
# STREAM
# =========================

def generate_answer_stream(question: str, context: str, history=None) -> Iterator[str]:
    with _http_session.post(
        f"{settings.ollama_base_url}/api/generate",
        json={
            "model": settings.ollama_chat_model,
            "prompt": _build_prompt(question, context, history),
            "system": SYSTEM_PROMPT,
            "stream": True,
            "options": _answer_options(),
        },
        stream=True,
        timeout=120,
    ) as response:

        response.raise_for_status()
        emitted = False

        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue

            chunk = requests.models.complexjson.loads(line)
            token = chunk.get("response", "")

            if token:
                emitted = True
                yield token

            if chunk.get("done"):
                break

        if not emitted:
            yield FALLBACK_MESSAGE