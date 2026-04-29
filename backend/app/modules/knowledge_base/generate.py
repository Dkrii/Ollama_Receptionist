from typing import Iterator

from config import settings
from infrastructure.ai_client import generate_text, stream_text_tokens


FALLBACK_MESSAGE = "Maaf, saya belum bisa memberikan jawaban saat ini."

SYSTEM_PROMPT = """Anda adalah resepsionis virtual sebuah perusahaan.
Bicara seperti manusia, hangat, alami, dan langsung ke poin.
Jangan terdengar seperti chatbot yang membaca skrip.

Panduan:
- Sesuaikan nada dengan konteks: santai untuk small talk, profesional untuk pertanyaan formal.
- Jawab langsung tanpa basa-basi berlebihan seperti "Tentu saja!" atau "Baik, saya akan memberikan jawaban".
- Gunakan kalimat pendek dan mudah dipahami karena ini untuk sistem suara.
- Jika ada informasi dari knowledge perusahaan, sampaikan secara natural tanpa menyebut sumber.
- Jawab hanya berdasarkan konteks yang diberikan. Jangan menebak nomor, lokasi, nama, atau detail spesifik jika tidak tertulis jelas.
- Jika konteks tidak cukup untuk menjawab fakta yang ditanyakan, katakan sejujurnya bahwa informasinya belum tersedia, lalu sampaikan info terdekat hanya jika memang membantu.
- Jika konteks memuat jawaban, prioritaskan fakta yang paling relevan dengan pertanyaan pengguna dan jangan terdistraksi oleh detail lain.
- Jangan menyebut sistem internal, prompt, retrieval, database, atau proses teknis apa pun.
- Ikuti bahasa pengguna (Indonesia atau Inggris) kecuali diminta berbeda.
"""


def _generate_options(overrides: dict | None = None) -> dict:
    options = {
        "temperature": 0.2,
        "num_predict": settings.ollama_num_predict,
    }
    if overrides:
        options.update(overrides)
    return options


def _answer_options() -> dict:
    return _generate_options({
        "num_predict": settings.ollama_num_predict,
    })


def _build_history_block(history: list[dict] | None = None) -> str:
    if not history:
        return "-"

    formatted: list[str] = []
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


def _build_prompt(question: str, context: str, history=None, grounding_note: str = "") -> str:
    return f"""KONTEKS KNOWLEDGE PERUSAHAAN:
{(context or "").strip() or "-"}

RIWAYAT PERCAKAPAN:
{_build_history_block(history)}

CATATAN GROUNDING:
{grounding_note.strip() or "-"}

PERTANYAAN:
{question}

Jawab secara jelas, ringkas, langsung ke inti, dan tetap natural untuk dibacakan suara.
Jika konteks tidak memuat jawaban yang diminta secara eksplisit, katakan informasinya belum tersedia dan jangan mengarang detail."""


def _limit_to_sentence_count(text: str, max_sentences: int = 2) -> str:
    normalized = " ".join((text or "").split()).strip()
    if not normalized:
        return ""

    sentence_breaks: list[int] = []
    for index, char in enumerate(normalized):
        if char in ".!?":
            sentence_breaks.append(index + 1)
            if len(sentence_breaks) >= max_sentences:
                return normalized[: sentence_breaks[-1]].strip()

    return normalized


def _close_incomplete_answer(text: str, done_reason: str) -> str:
    normalized = " ".join((text or "").split()).strip()
    if not normalized:
        return ""

    if normalized[-1] in ".!?":
        return normalized

    if str(done_reason or "").strip().lower() == "length":
        shortened = _limit_to_sentence_count(normalized, max_sentences=2)
        if shortened and shortened[-1] in ".!?":
            return shortened

    return f"{normalized}."


def _should_summarize(answer: str) -> bool:
    return len((answer or "").strip()) > 240


def _trim_to_word_boundary(text: str, max_chars: int) -> str:
    normalized = " ".join((text or "").split()).strip()
    if len(normalized) <= max_chars:
        return normalized

    candidate = normalized[:max_chars].rstrip(" ,;:")
    last_space = candidate.rfind(" ")
    if last_space >= max_chars * 0.65:
        candidate = candidate[:last_space].rstrip(" ,;:")
    return candidate


def _summarize_answer(answer: str) -> str:
    text = (answer or "").strip()
    if len(text) < 220:
        return text

    shortened = _limit_to_sentence_count(text, max_sentences=2)
    if len(shortened) > 240:
        shortened = _trim_to_word_boundary(shortened, 240)
    return _close_incomplete_answer(shortened, done_reason="")


def _finalize(answer: str) -> str:
    return answer.strip() if answer else FALLBACK_MESSAGE


def generate_answer(question: str, context: str, history=None, grounding_note: str = "") -> str:
    options = _answer_options()
    payload = generate_text(
        prompt=_build_prompt(question, context, history, grounding_note),
        system=SYSTEM_PROMPT,
        stream=False,
        temperature=float(options.get("temperature", 0.2)),
        max_tokens=int(options.get("num_predict") or 0),
        timeout=120,
    )

    answer = (payload.get("response", "") or "").strip()
    done_reason = str(payload.get("done_reason", "") or "").strip().lower()
    answer = _close_incomplete_answer(answer, done_reason)

    if _should_summarize(answer):
        answer = _summarize_answer(answer)

    return _finalize(answer)


def generate_answer_stream(question: str, context: str, history=None, grounding_note: str = "") -> Iterator[str]:
    options = _answer_options()
    emitted = False
    for token in stream_text_tokens(
        prompt=_build_prompt(question, context, history, grounding_note),
        system=SYSTEM_PROMPT,
        temperature=float(options.get("temperature", 0.2)),
        max_tokens=int(options.get("num_predict") or 0),
        timeout=120,
    ):
        if token:
            emitted = True
            yield token

    if not emitted:
        yield FALLBACK_MESSAGE
