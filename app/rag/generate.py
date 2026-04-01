import requests
import re
from typing import Iterator

from config import settings


_http_session = requests.Session()


FALLBACK_MESSAGE = "Maaf, saya belum menemukan informasi itu di knowledge base kami."

STOPWORDS = {
    "yang", "dan", "atau", "untuk", "dengan", "pada", "dari", "ke", "di", "ini", "itu",
    "the", "and", "for", "from", "with", "that", "have", "has", "are", "was", "were",
    "anda", "saya", "kami", "mereka", "kamu", "apa", "siapa", "berapa", "kapan", "dimana",
}


def _ollama_generate_options(overrides: dict | None = None) -> dict:
    options = {
        "temperature": 0.1,
        "num_predict": settings.ollama_num_predict,
        "num_ctx": settings.ollama_num_ctx,
    }
    if settings.ollama_num_thread > 0:
        options["num_thread"] = settings.ollama_num_thread
    if overrides:
        options.update(overrides)
    return options


SYSTEM_PROMPT = """Anda adalah virtual receptionist.
Aturan wajib:
1. Untuk pertanyaan faktual, jawab hanya berdasarkan konteks RAG yang diberikan.
2. Untuk sapaan atau small-talk (contoh: hai, halo, terima kasih), balas secara natural dan singkat.
3. Jika pertanyaan faktual tidak didukung konteks, jawab: 'Maaf, saya belum menemukan informasi itu di knowledge base kami.'
4. Jangan menambah fakta dari luar konteks.
5. Selalu gunakan Bahasa Indonesia yang natural dan sopan.
"""


SOCIAL_SYSTEM_PROMPT = """Anda adalah virtual receptionist.
Balas pesan pengguna secara natural, ramah, dan singkat (1-2 kalimat).
Jawaban harus berupa kalimat utuh yang jelas (bukan satu kata/label).
Jangan menambahkan fakta perusahaan yang tidak diminta.
Selalu gunakan Bahasa Indonesia yang natural dan sopan.
"""


SOCIAL_ROUTER_PROMPT = """Tentukan apakah pesan pengguna termasuk:
- social: sapaan/basa-basi/terima kasih/percakapan non-faktual.
- knowledge: permintaan informasi/fakta.

Jika social, balas dengan format persis:
social|<jawaban 1 kalimat utuh dalam Bahasa Indonesia, 6-20 kata>

Jika knowledge, balas dengan format persis:
knowledge|

Jangan output format lain.
"""


INDONESIAN_REWRITE_PROMPT = """Ubah kalimat berikut menjadi Bahasa Indonesia yang natural dan sopan.
Pertahankan maksud asli, ringkas, dan jangan menambah informasi baru.
Balas hanya hasil akhir tanpa penjelasan.
"""


_ENGLISH_HINT_RE = re.compile(r"\b(hello|hi|how|can|assist|today|thank|you|please|help)\b", re.IGNORECASE)


def classify_social_with_reply(question: str) -> tuple[str, str]:
    response = _http_session.post(
        f"{settings.ollama_base_url}/api/generate",
        json={
            "model": settings.ollama_chat_model,
            "prompt": question,
            "system": SOCIAL_ROUTER_PROMPT,
            "stream": False,
            "keep_alive": "30m",
            "options": _ollama_generate_options(
                {
                    "temperature": 0,
                    "num_predict": 64,
                    "num_ctx": 768,
                }
            ),
        },
        timeout=60,
    )
    response.raise_for_status()
    raw = (response.json().get("response", "") or "").strip()

    lowered = raw.lower()
    if lowered.startswith("knowledge"):
        return "knowledge", ""

    if lowered.startswith("social|"):
        return "social", raw.split("|", 1)[1].strip()

    if "|" in raw:
        left, right = raw.split("|", 1)
        if left.strip().lower() in {"social", "sosial"}:
            return "social", right.strip()

    return "social", ""


def generate_social_answer(question: str) -> str:
    response = _http_session.post(
        f"{settings.ollama_base_url}/api/generate",
        json={
            "model": settings.ollama_chat_model,
            "prompt": question,
            "system": SOCIAL_SYSTEM_PROMPT,
            "stream": False,
            "keep_alive": "30m",
            "options": _ollama_generate_options(
                {
                    "temperature": 0.2,
                    "num_predict": 80,
                    "num_ctx": 1024,
                }
            ),
        },
        timeout=60,
    )
    response.raise_for_status()
    answer = (response.json().get("response", "") or "").strip()
    return answer or "Halo, saya siap membantu."


def ensure_indonesian_text(text: str) -> str:
    source = (text or "").strip()
    if not source:
        return source

    if not _ENGLISH_HINT_RE.search(source):
        return source

    response = _http_session.post(
        f"{settings.ollama_base_url}/api/generate",
        json={
            "model": settings.ollama_chat_model,
            "prompt": source,
            "system": INDONESIAN_REWRITE_PROMPT,
            "stream": False,
            "keep_alive": "30m",
            "options": _ollama_generate_options(
                {
                    "temperature": 0,
                    "num_predict": 80,
                    "num_ctx": 1024,
                }
            ),
        },
        timeout=60,
    )
    response.raise_for_status()
    rewritten = (response.json().get("response", "") or "").strip()
    return rewritten or source


def _extractive_answer(question: str, context: str) -> str:
    lines = [line.strip() for line in context.splitlines() if line.strip()]
    if not lines:
        return FALLBACK_MESSAGE

    keywords = [token.lower() for token in question.replace("?", " ").split() if len(token) >= 4]
    for line in lines:
        lowered = line.lower()
        if any(keyword in lowered for keyword in keywords):
            return line

    return lines[0]


def _normalize_tokens(text: str) -> list[str]:
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower())
    return [token for token in cleaned.split() if len(token) >= 4 and token not in STOPWORDS]


def _question_is_relevant_to_context(question: str, context: str) -> bool:
    question_tokens = _normalize_tokens(question)
    if not question_tokens:
        return True

    context_tokens = set(_normalize_tokens(context))
    if not context_tokens:
        return False

    matched = sum(1 for token in question_tokens if token in context_tokens)
    coverage = matched / len(question_tokens)
    return coverage >= 0.25


def _answer_is_grounded(answer: str, context: str) -> bool:
    answer_tokens = _normalize_tokens(answer)
    if not answer_tokens:
        return False

    context_tokens = set(_normalize_tokens(context))
    if not context_tokens:
        return False

    matched = sum(1 for token in answer_tokens if token in context_tokens)
    coverage = matched / len(answer_tokens)
    return coverage >= 0.3


def _strict_fallback_enabled() -> bool:
    return settings.rag_strict_mode and settings.rag_fallback_policy.lower() == "strict"


def generate_answer(question: str, context: str) -> str:
    if not context.strip():
        return FALLBACK_MESSAGE

    if _strict_fallback_enabled() and not _question_is_relevant_to_context(question, context):
        return FALLBACK_MESSAGE

    prompt = f"""KONTEKS RAG:
{context}

PERTANYAAN PENGGUNA:
{question}

Jawab sesuai aturan."""

    response = _http_session.post(
        f"{settings.ollama_base_url}/api/generate",
        json={
            "model": settings.ollama_chat_model,
            "prompt": prompt,
            "system": SYSTEM_PROMPT,
            "stream": False,
            "keep_alive": "30m",
            "options": _ollama_generate_options(),
        },
        timeout=120,
    )
    response.raise_for_status()
    answer = response.json().get("response", "").strip()

    if context.strip() and answer == FALLBACK_MESSAGE:
        return _extractive_answer(question, context)

    if _strict_fallback_enabled() and context.strip() and not _answer_is_grounded(answer, context):
        return FALLBACK_MESSAGE

    return answer or FALLBACK_MESSAGE


def generate_answer_stream(question: str, context: str) -> Iterator[str]:
    if not context.strip():
        yield FALLBACK_MESSAGE
        return

    if _strict_fallback_enabled() and not _question_is_relevant_to_context(question, context):
        yield FALLBACK_MESSAGE
        return

    prompt = f"""KONTEKS RAG:
{context}

PERTANYAAN PENGGUNA:
{question}

Jawab sesuai aturan."""

    with _http_session.post(
        f"{settings.ollama_base_url}/api/generate",
        json={
            "model": settings.ollama_chat_model,
            "prompt": prompt,
            "system": SYSTEM_PROMPT,
            "stream": True,
            "keep_alive": "30m",
            "options": _ollama_generate_options(),
        },
        timeout=120,
        stream=True,
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

            if chunk.get("done") is True:
                break

        if not emitted:
            yield FALLBACK_MESSAGE
