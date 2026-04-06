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

IMPORTANT_SHORT_TOKENS = {"jam", "hrd", "it", "she", "qcc", "ojt", "k3"}
REQUIRED_ANSWER_ANCHORS = {"jam", "visi", "misi", "muster", "toilet", "mushola", "alamat", "email", "telepon", "fax"}
LOCATION_TOKENS = {"dimana", "lokasi", "letak", "berada", "sebelah", "lantai", "ruang", "area", "gedung", "mana"}


def _ollama_generate_options(overrides: dict | None = None) -> dict:
    options = {
        "temperature": 0,
        "num_predict": settings.ollama_num_predict,
        "num_ctx": settings.ollama_num_ctx,
    }
    if settings.ollama_num_thread > 0:
        options["num_thread"] = settings.ollama_num_thread
    if overrides:
        options.update(overrides)
    return options


def _clamp_num_predict(value: int) -> int:
    ceiling = max(32, settings.ollama_num_predict)
    return max(32, min(value, ceiling))


SYSTEM_PROMPT = """Anda adalah virtual receptionist.
Aturan wajib:
1. Untuk pertanyaan faktual, jawab hanya berdasarkan konteks RAG yang diberikan.
2. Untuk sapaan atau small-talk (contoh: hai, halo, terima kasih), balas secara natural dan singkat.
3. Jika pertanyaan faktual tidak didukung konteks, jawab: 'Maaf, saya belum menemukan informasi itu di knowledge base kami.'
4. Jangan menambah fakta dari luar konteks.
5. Selalu gunakan Bahasa Indonesia yang natural dan sopan.
6. Gunakan format poin hanya jika pengguna secara eksplisit meminta daftar, poin, atau ringkasan per item.
7. Jika pengguna menanyakan topik umum seperti profil perusahaan, jawab dalam 1-2 paragraf ringkas yang mengikuti fakta utama pada konteks, bukan daftar bernomor.
8. Jika konteks berisi lokasi/fasilitas, jawab langsung dengan lokasi yang paling relevan dari konteks.
9. Pastikan jawaban ditutup dengan kalimat yang utuh, tidak menggantung di tengah poin.
10. Jika konteks hanya menyebut judul topik tanpa detail faktual yang cukup, gunakan fallback dan jangan menebak.
11. Secara default, jaga jawaban tetap singkat. Hanya beri detail panjang jika pengguna memang meminta detail.
12. Untuk pertanyaan umum tentang profil perusahaan atau "apa yang Anda ketahui", berikan ringkasan singkat terlebih dahulu lalu tawarkan secara natural apakah pengguna ingin versi lebih detail.
13. Jika pengguna pada giliran berikutnya meminta versi detail, lebih lengkap, atau lebih rinci, gunakan riwayat percakapan untuk memahami topik yang sama lalu berikan penjelasan lebih lengkap berdasarkan konteks.
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
                    "num_predict": 48,
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
                    "num_predict": 48,
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

    def _looks_like_heading(line: str) -> bool:
        compact = line.strip()
        if len(compact) <= 24:
            return True
        return bool(re.match(r"^(bab\b|\d+(\.\d+)+\s)", compact.lower()))

    keywords = _normalize_tokens(question)
    anchor_keyword = keywords[0] if keywords else ""
    minimum_matches = max(1, min(2, len(keywords)))
    for line in lines:
        line_tokens = set(_normalize_tokens(line))
        matched = sum(1 for keyword in keywords if keyword in line_tokens)
        if (
            matched >= minimum_matches
            and (not anchor_keyword or anchor_keyword in line_tokens)
            and not _looks_like_heading(line)
        ):
            return line

    return FALLBACK_MESSAGE


def _normalize_tokens(text: str) -> list[str]:
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower())
    return [
        token
        for token in cleaned.split()
        if (len(token) >= 4 or token in IMPORTANT_SHORT_TOKENS) and token not in STOPWORDS
    ]


def _normalize_history(history: list[dict] | None) -> list[dict]:
    normalized: list[dict] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized[-6:]


def _render_history(history: list[dict] | None) -> str:
    normalized = _normalize_history(history)
    if not normalized:
        return "-"

    rendered = []
    for item in normalized:
        speaker = "User" if item["role"] == "user" else "Assistant"
        rendered.append(f"{speaker}: {item['content']}")
    return "\n".join(rendered)


def _question_focus_tokens(question: str) -> list[str]:
    return [token for token in _normalize_tokens(question) if token not in LOCATION_TOKENS]


def _asks_for_detail(question: str, history: list[dict] | None = None) -> bool:
    lowered = (question or "").lower().strip()
    detail_markers = (
        "detail",
        "rinci",
        "lebih detail",
        "lebih lengkap",
        "secara lengkap",
        "jelaskan lebih",
        "versi detail",
        "elaborasi",
        "perjelas",
    )
    if any(marker in lowered for marker in detail_markers):
        return True

    normalized_history = _normalize_history(history)
    if normalized_history and len(_normalize_tokens(question)) <= 3:
        short_followup_markers = {"lanjutkan", "lanjut", "detailnya", "lengkapnya", "rinciannya"}
        if any(marker in lowered for marker in short_followup_markers):
            return True

    return False


def _is_general_profile_question(question: str) -> bool:
    lowered = (question or "").lower()
    profile_markers = (
        "profil perusahaan",
        "profil pt",
        "apa yang anda ketahui",
        "apa saja yang anda ketahui",
        "tentang pt",
        "tentang perusahaan",
        "company profile",
    )
    return any(marker in lowered for marker in profile_markers)


def _is_profile_topic(question: str, history: list[dict] | None = None) -> bool:
    if _is_general_profile_question(question):
        return True

    normalized_history = _normalize_history(history)
    joined = " ".join(item["content"].lower() for item in normalized_history[-4:])
    profile_markers = ("profil", "perusahaan", "pt akebono", "akebono brake astra indonesia")
    return any(marker in joined for marker in profile_markers)


def _build_effective_question(question: str, history: list[dict] | None = None) -> str:
    normalized_history = _normalize_history(history)
    if not normalized_history or not _asks_for_detail(question, history=history):
        return question

    recent_user_messages = [
        item["content"]
        for item in normalized_history
        if item["role"] == "user"
    ]
    if not recent_user_messages:
        return question

    previous_topic = recent_user_messages[-1]
    if previous_topic.strip().lower() == question.strip().lower() and len(recent_user_messages) >= 2:
        previous_topic = recent_user_messages[-2]

    if not previous_topic:
        return question

    return f"{previous_topic}\nPertanyaan lanjutan: {question}"


def _is_location_question(question: str) -> bool:
    lowered = (question or "").lower()
    focus_tokens = _question_focus_tokens(question)
    return (
        "di mana" in lowered
        or any(token in lowered for token in LOCATION_TOKENS)
        or (len(focus_tokens) <= 2 and "dimana" in lowered.replace(" ", ""))
    )


def _format_structured_location_answer(subject: str, location: str) -> str:
    subject = (subject or "").strip()
    location = (location or "").strip()
    if not subject or not location:
        return FALLBACK_MESSAGE

    return f"{subject} berada di {location}."


def _extract_structured_answer(question: str, context: str) -> str | None:
    if not context.strip():
        return None

    focus_tokens = _question_focus_tokens(question)
    if not focus_tokens:
        return None

    focus_phrase = " ".join(focus_tokens).strip()
    best_score = 0
    best_cells: list[str] | None = None

    for line in context.splitlines():
        if "|" not in line:
            continue

        cells = [cell.strip() for cell in line.split("|") if cell.strip()]
        if len(cells) < 2:
            continue

        subject_tokens = set(_normalize_tokens(cells[0]))
        line_tokens = set(_normalize_tokens(line))
        subject_match = sum(1 for token in focus_tokens if token in subject_tokens)
        line_match = sum(1 for token in focus_tokens if token in line_tokens)
        exact_subject = int(cells[0].strip().lower() == focus_phrase.lower())
        starts_with_subject = int(cells[0].strip().lower().startswith(focus_phrase.lower()))
        score = (exact_subject * 10) + (starts_with_subject * 6) + (subject_match * 4) + line_match

        if score > best_score:
            best_score = score
            best_cells = cells

    if not best_cells or best_score < 4:
        return None

    if _is_location_question(question):
        return _format_structured_location_answer(best_cells[0], best_cells[1])

    return None


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


def _answer_has_required_anchor(question: str, answer: str) -> bool:
    question_tokens = _normalize_tokens(question)
    required = [token for token in question_tokens if token in REQUIRED_ANSWER_ANCHORS]
    if not required:
        return True

    lowered_answer = (answer or "").lower()
    return any(token in lowered_answer for token in required)


def _introduces_unsupported_numbers(answer: str, context: str) -> bool:
    answer_numbers = set(re.findall(r"\b\d{1,2}(?:[.:]\d{2})?\b", answer or ""))
    if not answer_numbers:
        return False

    context_numbers = set(re.findall(r"\b\d{1,2}(?:[.:]\d{2})?\b", context or ""))
    return not answer_numbers.issubset(context_numbers)


def _strict_fallback_enabled() -> bool:
    return settings.rag_strict_mode and settings.rag_fallback_policy.lower() == "strict"


def _is_fallback_like(answer: str) -> bool:
    lowered = (answer or "").strip().lower()
    if not lowered:
        return False

    fallback_markers = (
        FALLBACK_MESSAGE.lower(),
        "belum menemukan informasi",
        "belum memiliki datanya",
        "di luar cakupan",
    )
    return any(marker in lowered for marker in fallback_markers)


def _resolve_rag_fast_answer(question: str, context: str) -> str | None:
    structured_answer = _extract_structured_answer(question, context)
    if structured_answer and structured_answer != FALLBACK_MESSAGE:
        return structured_answer
    return None


def _knowledge_style_instruction(question: str, history: list[dict] | None = None) -> str:
    if _asks_for_detail(question, history=history):
        if _is_profile_topic(question, history=history):
            return (
                "Pengguna meminta versi lebih detail setelah sebelumnya menerima ringkasan singkat tentang profil perusahaan. "
                "Jangan mengulang paragraf pembuka yang sama dan jangan menawarkan detail lagi. Lanjutkan topik yang sama "
                "dengan 2-3 paragraf prose natural tanpa heading atau bullet. Fokus pada identitas perusahaan, sejarah singkat, "
                "bidang usaha, visi, misi, nilai inti, segmen pasar, dan standar kualitas. Jangan melebar ke layout gedung, "
                "lokasi ruangan, atau fasilitas kecuali pengguna memintanya. Batasi jawaban sekitar 6-8 kalimat dan pastikan "
                "ditutup dengan kalimat yang utuh."
            )
        return (
            "Pengguna meminta penjelasan lebih detail. Berikan jawaban yang lebih lengkap dan terstruktur, "
            "tetap fokus pada topik yang sama di riwayat percakapan, dan tutup dengan kalimat lengkap."
        )
    if _is_general_profile_question(question):
        return (
            "Ini pertanyaan umum tentang profil perusahaan. Berikan ringkasan singkat 1 paragraf padat sekitar 3-5 kalimat terlebih dahulu, "
            "tanpa daftar atau heading, lalu tutup dengan satu kalimat natural yang menawarkan apakah pengguna ingin penjelasan yang lebih detail."
        )
    return "Jawab singkat, langsung ke inti, dan cukup 1-2 paragraf kecuali pengguna meminta detail."


def _estimate_knowledge_num_predict(question: str, context: str, history: list[dict] | None = None) -> int:
    lowered = (question or "").lower()
    focus_tokens = _question_focus_tokens(question)
    context_length = len(context or "")
    short_budget = _clamp_num_predict(settings.ollama_num_predict_short)
    default_budget = _clamp_num_predict(settings.ollama_num_predict_default)
    long_budget = _clamp_num_predict(settings.ollama_num_predict_long)

    if _is_location_question(question):
        return short_budget

    if _asks_for_detail(question, history=history):
        return long_budget

    if _is_general_profile_question(question):
        return default_budget

    if any(term in lowered for term in ("profil", "sejarah", "visi", "misi", "ringkasan", "ringkas")):
        return min(long_budget, max(default_budget, 224))

    if len(focus_tokens) <= 3 and context_length <= 2200:
        return short_budget

    return default_budget


def _build_knowledge_prompt(question: str, context: str, history: list[dict] | None = None) -> str:
    style_instruction = _knowledge_style_instruction(question, history=history)
    rendered_history = _render_history(history)
    return f"""RIWAYAT PERCAKAPAN:
{rendered_history}

KONTEKS RAG:
{context}

PERTANYAAN PENGGUNA:
{question}

INSTRUKSI GAYA JAWABAN:
{style_instruction}

Jawab sesuai aturan."""


def _answer_looks_complete(answer: str) -> bool:
    text = (answer or "").strip()
    if not text:
        return False
    return bool(re.search(r"[.!?)]['\"]?$", text))


def _tail_fragment(text: str, max_chars: int = 220) -> str:
    value = (text or "").strip()
    if len(value) <= max_chars:
        return value
    return value[-max_chars:]


def _continue_answer(
    question: str,
    context: str,
    partial_answer: str,
    history: list[dict] | None = None,
    num_predict: int = 160,
) -> str:
    partial_tail = _tail_fragment(partial_answer)
    prompt = f"""RIWAYAT PERCAKAPAN:
{_render_history(history)}

KONTEKS RAG:
{context}

PERTANYAAN PENGGUNA:
{question}

FRAGMEN AKHIR JAWABAN SEBELUMNYA YANG TERPOTONG:
{partial_tail}

Tuliskan hanya lanjutan paling akhir yang masih kurang dari jawaban sebelumnya.
Jika fragmen terakhir terpotong di tengah kata atau kalimat, lanjutkan langsung dari sana.
Jangan mengulang paragraf atau poin yang sudah dijelaskan.
Cukup 1-2 kalimat penutup yang menyelesaikan jawaban secara utuh."""

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
                    "num_predict": _clamp_num_predict(num_predict),
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
    reason = (done_reason or "").lower()
    attempts = 0

    while completed and attempts < 1:
        needs_more = reason == "length" and not _answer_looks_complete(completed)
        if not needs_more:
            break

        continuation = _continue_answer(
            question,
            context,
            completed,
            history=history,
            num_predict=settings.ollama_num_predict_short,
        )
        if not continuation:
            break

        completed = _merge_with_overlap(completed, continuation)
        reason = ""
        attempts += 1

    return completed


def generate_answer(question: str, context: str, history: list[dict] | None = None) -> str:
    effective_question = _build_effective_question(question, history=history)

    if not context.strip():
        return FALLBACK_MESSAGE

    if _strict_fallback_enabled() and not _question_is_relevant_to_context(effective_question, context):
        return FALLBACK_MESSAGE

    fast_answer = _resolve_rag_fast_answer(effective_question, context)
    if fast_answer:
        return fast_answer

    prompt = _build_knowledge_prompt(question, context, history=history)
    num_predict = _estimate_knowledge_num_predict(question, context, history=history)

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
                    "num_predict": num_predict,
                }
            ),
        },
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    answer = (payload.get("response", "") or "").strip()
    done_reason = str(payload.get("done_reason", "") or payload.get("doneReason", "") or "").lower()

    answer = _extend_answer_if_needed(question, context, answer, done_reason, history=history)

    if _is_fallback_like(answer):
        return FALLBACK_MESSAGE

    if not _answer_has_required_anchor(effective_question, answer):
        return _extractive_answer(effective_question, context)

    if _introduces_unsupported_numbers(answer, context):
        return _extractive_answer(effective_question, context)

    if context.strip() and not _answer_is_grounded(answer, context):
        return _extractive_answer(effective_question, context)

    return answer or FALLBACK_MESSAGE


def generate_answer_stream(question: str, context: str, history: list[dict] | None = None) -> Iterator[str]:
    effective_question = _build_effective_question(question, history=history)

    if not context.strip():
        yield FALLBACK_MESSAGE
        return

    if _strict_fallback_enabled() and not _question_is_relevant_to_context(effective_question, context):
        yield FALLBACK_MESSAGE
        return

    fast_answer = _resolve_rag_fast_answer(effective_question, context)
    if fast_answer:
        yield fast_answer
        return

    prompt = _build_knowledge_prompt(question, context, history=history)
    num_predict = _estimate_knowledge_num_predict(question, context, history=history)

    with _http_session.post(
        f"{settings.ollama_base_url}/api/generate",
        json={
            "model": settings.ollama_chat_model,
            "prompt": prompt,
            "system": SYSTEM_PROMPT,
            "stream": True,
            "keep_alive": "30m",
            "options": _ollama_generate_options(
                {
                    "num_predict": num_predict,
                }
            ),
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
        extended_answer = _extend_answer_if_needed(
            question,
            context,
            full_answer,
            done_reason,
            history=history,
        )
        if extended_answer and extended_answer != full_answer:
            continuation_text = extended_answer[len(full_answer):].strip()
            if continuation_text:
                yield f" {continuation_text}".rstrip()
                emitted = True

        if not emitted:
            yield FALLBACK_MESSAGE
