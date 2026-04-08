# Virtual Receptionist Kiosk (Docker + Ollama + Pure RAG)

## Stack
- FastAPI (UI + API)
- Ollama (`qwen2.5:3b` + `nomic-embed-text`)
- ChromaDB
- Browser-based STT/TTS (Web Speech API)

## 1) Setup
1. Copy env file:
   - `copy .env.example .env`
2. Start infrastructure:
   - `docker compose up -d ollama chroma app`
3. Pull models:
   - `docker compose run --rm init-model`
4. Open app:
   - `http://localhost:8000`

## 2) Add Knowledge
Put your files into `knowledge/`:
- `.txt`
- `.md`
- `.pdf`
- `.docx`

Then reindex:
- `POST http://localhost:8000/api/reindex`
- PowerShell: `Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/reindex`

## 3) Chat API
`POST /api/chat`

Body:
```json
{
  "message": "Jam operasional kantor?"
}
```

### Employee Contact Flow API
`POST /api/chat/contact-flow`

Body:
```json
{
  "message": "tolong hubungi karyawan budi",
  "conversation_id": null,
  "history": [],
  "flow_state": { "stage": "idle" }
}
```

Response (handled by contact flow):
```json
{
  "handled": true,
  "answer": "Saya menemukan beberapa karyawan...",
  "conversation_id": "...",
  "flow_state": {
    "stage": "await_disambiguation",
    "action": "notify",
    "candidates": []
  }
}
```

Alur ini dipakai UI `/` dan `/dev` untuk:
- intent "hubungi karyawan"
- pencarian nama/divisi dari data karyawan panel admin
- disambiguasi jika kandidat > 1
- konfirmasi ya/tidak
- aksi `notify` (default) atau `call` (queue placeholder)
- feedback suara (TTS) dari browser

Response:
```json
{
  "answer": "...",
  "conversation_id": "c3f6c9c6-5a48-4bcb-9b54-3fc8ad18f6b7",
  "citations": [
    {
      "content": "...",
      "metadata": { "source": "faq.txt", "path": "...", "chunk_index": 0 },
      "score": 0.81
    }
  ]
}
```

## 4) Pure RAG Rules
- Jawaban hanya dari konteks hasil retrieval.
- Jika konteks tidak cukup, jawaban fallback:
  - `Maaf, saya belum menemukan informasi itu di knowledge base kami.`

## 5) Notes
- STT/TTS dijalankan di browser (lebih stabil di Windows Docker Desktop).
- Port aplikasi di-bind ke localhost (`127.0.0.1:8000`).
- Source code `app/` di-mount ke container `kiosk-app`, dan backend dijalankan dengan `uvicorn --reload` di Docker Compose agar perubahan Python/HTML/CSS/JS langsung terbaca tanpa `docker compose build app`.
- SQLite memory percakapan disimpan di Docker named volume agar lebih stabil untuk data aplikasi dibanding bind mount source code.
- Jika mengubah dependency Python (`requirements.txt`), tetap perlu rebuild image app.

### Alur Chat/RAG
- Diagram dan penjelasan alur request -> retrieval -> jawaban ada di [docs/chat-rag-flow.md](docs/chat-rag-flow.md)

### Latency tuning (tetap pakai `qwen2.5:3b`)
- `RAG_TOP_K=2` untuk menjaga retrieval tetap fokus.
- `RAG_MAX_CONTEXT_CHARS=1600` untuk membatasi panjang konteks.
- `OLLAMA_NUM_PREDICT=160` untuk membatasi panjang jawaban default.
- `OLLAMA_NUM_PREDICT_LONG=320` untuk pertanyaan yang memang meminta detail.
- `OLLAMA_NUM_CTX=2048` untuk menurunkan beban context window.
- `OLLAMA_NUM_THREAD=0` biarkan otomatis, atau isi jumlah core CPU jika ingin pinning manual.

### Fallback policy
- `RAG_FALLBACK_POLICY=context_only` (default): selama retrieval menemukan konteks, AI tetap menjawab dari konteks.
- `RAG_FALLBACK_POLICY=strict`: aktifkan fallback agresif untuk pertanyaan/jawaban yang dinilai kurang relevan.

### Chat session memory
- SQLite disimpan di `/workspace/runtime/chat.sqlite3` di dalam container, dengan persistence melalui Docker named volume `chat_runtime`.
- Backend mengelola `conversation_id` sebagai source of truth memory percakapan.
- Frontend menyimpan `conversation_id` di `sessionStorage` dan menghapus sesi setelah idle 5 menit.

## 6) Windows Kiosk Mode (Manual)

- Start stack: `docker compose up -d ollama chroma app`
- Open UI: `http://localhost:8000`
- Stop stack: `docker compose stop app chroma ollama`
