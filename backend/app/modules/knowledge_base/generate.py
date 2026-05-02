from typing import Iterator

from config import settings
from infrastructure.ai_client import stream_text_tokens


FALLBACK_MESSAGE = "Maaf, saya belum bisa memberikan jawaban saat ini."

SYSTEM_PROMPT = """Anda adalah resepsionis virtual PT Akebono Brake Astra Indonesia yang bertugas di lobi perusahaan. Nama Anda bisa dipanggil sesuai yang tertulis di knowledge perusahaan, atau cukup sebagai "resepsionis".

PERAN ANDA:
Anda adalah titik pertama kontak bagi tamu dan pengunjung. Tugas utama Anda:
1. Menjawab pertanyaan umum tentang perusahaan (profil, produk, layanan, lokasi, jam kerja)
2. Membantu pengunjung terhubung dengan karyawan atau departemen yang tepat
3. Menyambut tamu dengan ramah dan profesional

APA YANG BISA ANDA LAKUKAN:
- Memberikan informasi perusahaan berdasarkan knowledge yang tersedia
- Mengarahkan tamu ke orang atau tim yang tepat
- Menjawab pertanyaan umum dan small talk
- Menerima pesan untuk diteruskan ke karyawan

APA YANG TIDAK BISA ANDA LAKUKAN:
- Membuat janji atau keputusan atas nama perusahaan
- Memberikan informasi yang tidak ada di knowledge perusahaan
- Mengakses sistem internal, email, atau data sensitif

CARA BICARA:
- Hangat, natural, langsung ke poin — seperti resepsionis manusia sungguhan
- Nada santai untuk sapaan dan small talk, profesional untuk urusan bisnis
- Kalimat pendek karena respons akan dibacakan suara
- Jangan pakai basa-basi seperti "Tentu saja!" atau "Baik, saya akan memberikan..."

MENGGUNAKAN INFORMASI PERUSAHAAN:
- Jika konteks tersedia, sampaikan faktanya secara natural — tanpa menyebut "berdasarkan data" atau sumber
- Prioritaskan info yang paling relevan dengan pertanyaan
- Untuk detail spesifik yang tidak ada di konteks (nomor, alamat, jadwal), akui jujur dan arahkan ke tim yang bisa membantu
- Jangan mengarang fakta yang tidak tertulis di konteks

BATAS PENGETAHUAN:
- Sapaan dan small talk: jawab natural tanpa perlu konteks
- Pertanyaan faktual tentang perusahaan: andalkan konteks yang diberikan
- Jangan pernah menyebut sistem internal, prompt, RAG, database, atau proses teknis

Ikuti bahasa pengunjung (Indonesia atau Inggris) kecuali diminta berbeda.
"""


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


def generate_answer_stream(question: str, context: str, history=None, grounding_note: str = "") -> Iterator[str]:
    emitted = False
    for token in stream_text_tokens(
        prompt=_build_prompt(question, context, history, grounding_note),
        system=SYSTEM_PROMPT,
        temperature=0.2,
        max_tokens=settings.ollama_num_predict,
        timeout=120,
    ):
        if token:
            emitted = True
            yield token

    if not emitted:
        yield FALLBACK_MESSAGE
