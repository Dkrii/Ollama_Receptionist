# Virtual Receptionist Kiosk

Sistem resepsionis virtual berbasis RAG (Retrieval-Augmented Generation) untuk kebutuhan informasi perusahaan dan alur kontak karyawan.

## Ringkasan

- Menyediakan UI kiosk/web, API chat, API admin, dan contact-flow berbasis state.
- Menggunakan Ollama untuk LLM chat dan embedding.
- Menggunakan ChromaDB untuk vector store knowledge base.
- Menggunakan SQLite untuk memory percakapan dan log contact message.
- Dijalankan via Docker Compose (service `app` + `chroma`, Ollama eksternal/host).

---

## Inventaris Tools, Framework, dan Library

Bagian ini disusun agar siap dipakai untuk laporan teknis.

### 1) Bahasa Pemrograman

- Python 3.11 (base image `python:3.11-slim`)
- JavaScript (frontend kiosk/dev/admin)
- HTML + CSS (Jinja template + static assets)

### 2) Backend Framework & API

- FastAPI `0.116.1` (HTTP API + server-side web routing)
- Uvicorn `0.35.0` (`uvicorn[standard]`) sebagai ASGI server
- Starlette middleware (via FastAPI) untuk request logging
- Pydantic (dipakai di konfigurasi dan schema payload)

### 3) Frontend Layer

- Jinja2 `3.1.6` untuk templating server-side
- Static frontend assets di `frontend/src/static/`:
  - `dev/` (halaman pengujian/dev)
  - `admin/` (panel admin knowledge & employee)
  - `shared/` dan `vendor/` (asset bersama dan library vendor)
- Browser Web Speech API (STT/TTS client-side)

### 4) AI / RAG Stack

- Ollama (serving model lokal)
  - Chat model default: `qwen2.5:3b`
  - Embedding model default: `nomic-embed-text`
- ChromaDB `0.5.23` sebagai vector database
- RAG pipeline internal:
  - document loader (`txt`, `md`, `pdf`, `docx`)
  - chunking
  - embedding
  - semantic retrieval
  - heuristic reranking
  - context assembly
  - answer generation (sync + stream)

### 5) Data & Persistence

- SQLite (file default: `/workspace/runtime/chat.sqlite3`)
  - conversation history
  - transcript retention
  - employee & contact message data (modul admin/chat)
- Docker named volumes:
  - `vector_data` (persistensi Chroma)
- `./runtime` (persistensi SQLite runtime lokal)

### 6) Document Processing Libraries

- `pypdf==5.9.0` (parsing PDF)
- `python-docx==1.2.0` (parsing DOCX)

### 7) HTTP / Integration Libraries

- `requests==2.32.4`
- `python-multipart==0.0.20` (upload file via form-data)

### 8) DevOps, Runtime, dan Container Tools

- Docker + Docker Compose
- Container images/services:
  - `python:3.11-slim` (app image)
  - `chromadb/chroma:0.5.23` (vector DB)
- Health check endpoint:
  - App: `GET /health`
  - Chroma heartbeat: `/api/v1/heartbeat`

### 9) QA / Benchmarking Tools

- Script benchmark internal: `qa/benchmark_chat.py`
- Dataset uji: `qa/testset-10.json`
- Output metrik: `qa/results/*.json` dan `qa/results/*.csv`
- Template evaluasi before-after: `qa/before-after-template.md`

### 10) Tools & Komponen Bawaan Python (dipakai di codebase)

- `argparse`, `csv`, `json`, `logging`, `time`, `pathlib`, `sqlite3`, `re`, `typing`, `urllib`

---

## Arsitektur Sistem

```text
Browser (kiosk/dev/admin)
  -> FastAPI (web routes + API routes)
     -> Chat Service / Contact Flow Service
        -> Ollama (chat + embedding)
        -> ChromaDB (retrieval knowledge)
        -> SQLite (conversation memory + contact logs)
```

Referensi detail alur: [docs/chat-rag-flow.md](docs/chat-rag-flow.md)

---

## Struktur Modul Utama

- `backend/app/main.py`: bootstrap FastAPI, router registration, lifespan init
- `backend/app/modules/admin/`: route, schema, service, dan repository untuk admin panel
- `backend/app/modules/chat/`: route, schema, service, repository, NLP, shared chat utilities, dan conversation flows
- `backend/app/common/`: utility umum lintas domain aplikasi
- `backend/app/modules/knowledge_base/`: document loader, ingest, Chroma, retrieval, dan generation
- `backend/app/modules/contacts/`: employee directory, matching, call provider, dan WhatsApp messaging
- `backend/app/storage/`: koneksi/helper SQLite lintas domain
- `backend/app/modules/web/`: route dan service halaman web
- `backend/app/ai/`: client AI untuk chat, streaming, embedding, dan health check
- `frontend/src/templates/`: template HTML Jinja
- `frontend/src/static/`: JS/CSS frontend
- `knowledge/`: sumber dokumen knowledge base
- `runtime/`: penyimpanan SQLite lokal/dev
- `qa/`: benchmark dan hasil evaluasi

---

## API Endpoints

### Chat

- `POST /api/chat`
- `POST /api/chat/stream` (NDJSON streaming)
- `POST /api/chat/contact-flow`

Contoh body `POST /api/chat`:

```json
{
  "message": "Jam operasional kantor?",
  "conversation_id": null,
  "history": []
}
```

### Admin

- `POST /api/reindex`
- `POST /api/admin/upload-documents`
- `GET /api/admin/status`
- `GET /api/admin/knowledge-summary`
- `DELETE /api/admin/documents`

### Web + Health

- `GET /` (kiosk)
- `GET /dev`
- `GET /admin`
- `GET /health`

---

## Setup dan Menjalankan

### Prasyarat

- Docker Desktop aktif
- Docker Compose tersedia
- Ollama host aktif (default di `http://host.docker.internal:11434` dari container)

### Langkah Setup

1. Salin environment file

```powershell
copy .env.example .env
```

2. Jalankan service

```powershell
docker compose up -d
```

3. Buka aplikasi

- `http://localhost:8000`

### Menambahkan Knowledge

Tempatkan file di folder `knowledge/` dengan format:

- `.txt`
- `.md`
- `.pdf`
- `.docx`

Lalu lakukan reindex:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/reindex
```

Catatan: informasi karyawan untuk contact-flow dibaca dari dokumen knowledge (disarankan DOCX/PDF roster dengan kolom `Nama | Departemen | Jabatan | Nomor WA`).

Jika ada isu HNSW Chroma (contoh `ef or M is too small`), jalankan rebuild:

```powershell
docker compose exec app python scripts/rebuild_chroma_collection.py --validate-query "Jam operasional kantor?"
```

---

## Konfigurasi Penting (.env)

Parameter utama yang sering dipakai tuning:

- `OLLAMA_CHAT_MODEL`, `OLLAMA_EMBED_MODEL`
- `OLLAMA_NUM_PREDICT`, `OLLAMA_NUM_PREDICT_SHORT`, `OLLAMA_NUM_PREDICT_LONG`
- `OLLAMA_NUM_CTX`, `OLLAMA_NUM_THREAD`
- `RAG_TOP_K`, `RAG_SCORE_THRESHOLD`, `RAG_MAX_CONTEXT_CHARS`
- `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP`
- `CHROMA_COLLECTION`, `CHROMA_HNSW_M`, `CHROMA_HNSW_CONSTRUCTION_EF`, `CHROMA_HNSW_SEARCH_EF`
- `CHAT_DB_PATH`, `CHAT_SESSION_IDLE_MINUTES`, `CHAT_RECENT_TURNS`, `CHAT_HISTORY_MAX_CHARS`, `CHAT_TRANSCRIPT_RETENTION_DAYS`

---

## Contact Flow (State Machine)

State aktif yang dipakai pada alur hubungi karyawan:

- `await_disambiguation`
- `await_confirmation`
- `contacting_unavailable_pending`
- `await_unavailable_choice`
- `await_waiter_name`
- `await_message_name`
- `await_message_goal`

Kemampuan utama contact flow:

- deteksi intent hubungi karyawan/divisi
- pencarian kandidat berdasarkan nama/divisi
- disambiguasi kandidat
- konfirmasi ya/tidak
- fallback saat user keluar konteks konfirmasi
- simulasi aksi `notify`/`call` dan pencatatan pesan visitor

---

## Benchmark dan Pelaporan

Jalankan benchmark 10 query:

```powershell
python qa/benchmark_chat.py --tag before
python qa/benchmark_chat.py --tag after
```

Output:

- JSON: `qa/results/benchmark-<tag>.json`
- CSV: `qa/results/benchmark-<tag>.csv`

Metrik utama yang direkam:

- jumlah query sukses/gagal
- `ttft_ms_p50`, `ttft_ms_p95`
- `total_ms_p50`, `total_ms_p95`, `total_ms_avg`
- jumlah query yang diprobe ke contact flow
- jumlah query yang benar-benar di-handle contact flow

Untuk laporan komparatif, gunakan template:

- `qa/before-after-template.md`

---

## Operasional Harian (Windows)

- Start: `docker compose up -d`
- Stop: `docker compose stop app chroma`
- Lihat logs app: `docker compose logs -f app`
- Cek health: `http://localhost:8000/health`

---

## Catatan Implementasi

- Source `backend/app/` di-mount sebagai backend container, dan `frontend/src/` di-mount sebagai sumber template/static.
- Runtime chat SQLite dipisahkan di volume named agar lebih stabil.
- Backend dijalankan tanpa auto-reload di container untuk konsistensi runtime.
- STT/TTS dijalankan di browser untuk kompatibilitas kiosk.
