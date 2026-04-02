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

Response:
```json
{
  "answer": "...",
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
- Source code `app/` di-mount ke container `kiosk-app`, jadi perubahan HTML/CSS/JS langsung terbaca tanpa `docker compose build app`.
- Jika mengubah dependency Python (`requirements.txt`), tetap perlu rebuild image app.

### Latency tuning (tetap pakai `qwen2.5:3b`)
- `RAG_TOP_K=3` untuk mengurangi jumlah chunk yang diproses model.
- `RAG_MAX_CONTEXT_CHARS=3200` untuk membatasi panjang konteks.
- `OLLAMA_NUM_PREDICT=160` untuk membatasi panjang jawaban default.
- `OLLAMA_NUM_CTX=2048` untuk menurunkan beban context window.
- `OLLAMA_NUM_THREAD=0` biarkan otomatis, atau isi jumlah core CPU jika ingin pinning manual.

### Fallback policy
- `RAG_FALLBACK_POLICY=context_only` (default): selama retrieval menemukan konteks, AI tetap menjawab dari konteks.
- `RAG_FALLBACK_POLICY=strict`: aktifkan fallback agresif untuk pertanyaan/jawaban yang dinilai kurang relevan.

## 6) Windows Kiosk Mode (Manual)

- Start stack: `docker compose up -d ollama chroma app`
- Open UI: `http://localhost:8000`
- Stop stack: `docker compose stop app chroma ollama`
