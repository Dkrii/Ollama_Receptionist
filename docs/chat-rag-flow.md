# Chat/RAG Flow

Dokumen ini menjelaskan alur chat terbaru di aplikasi `Virtual Receptionist Kiosk`.

## Ringkasan

Sistem sekarang memakai jalur yang lebih sederhana:

1. Request masuk ke endpoint chat FastAPI bersama `conversation_id` bila tersedia.
2. Backend memuat riwayat sesi dari SQLite dan menyimpan turn user terbaru.
3. Pertanyaan user diubah menjadi embedding oleh Ollama.
4. Embedding query dipakai untuk mencari chunk paling relevan di ChromaDB.
5. Hasil retrieval direrank lagi dengan heuristic lexical, termasuk follow-up query ringan berbasis history.
6. Chunk terpilih digabung menjadi konteks knowledge perusahaan.
7. Ollama menyusun jawaban singkat dan langsung ke inti dengan riwayat percakapan sebelumnya.
8. Jawaban final disimpan ke SQLite dan API mengembalikan `answer`, `citations`, dan `conversation_id`.

Perubahan penting:

- Riwayat percakapan sekarang disimpan di SQLite
- Frontend memakai `conversation_id` untuk melanjutkan sesi kiosk
- Retrieval memakai follow-up heuristic ringan dari history
- Metadata, source, embedding, dan dokumen knowledge tetap disimpan di ChromaDB

## Diagram Alur

```mermaid
flowchart TD
    A[User mengirim pertanyaan] --> B[/api/chat atau /api/chat/stream]
    B --> C[Resolve conversation_id]
    C --> D[Load recent history dari SQLite]
    D --> E[Simpan turn user]
    E --> F[retrieve_context]
    F --> G[Ollama embeddings untuk query]
    G --> H[Chroma collection.query by embedding]
    H --> I[Rerank hasil dengan lexical metrics]
    I --> J{Konteks relevan?}
    J -- Ya --> K[Gabungkan top-k chunk jadi context]
    J -- Tidak --> L[Context kosong]
    K --> M[generate_answer / generate_answer_stream]
    L --> M
    M --> N[Simpan turn assistant ke SQLite]
    N --> O[API mengembalikan answer + citations + conversation_id]
```

## Detail Per File

### 1. Entry point API

- Route chat ada di [app/api/chat/routes.py](../app/api/chat/routes.py)
- Route meneruskan request ke `ChatService`
- Route menerima `conversation_id` dan tetap kompatibel dengan `history` dari frontend

### 2. Retrieval context

File utama:

- [app/rag/retrieve.py](../app/rag/retrieve.py)

Yang dilakukan:

1. Query dipakai apa adanya tanpa rewrite follow-up
2. Jika query pendek atau referensial, query digabung ringan dengan last user turn sebelumnya
3. Query diubah menjadi embedding oleh Ollama
4. Chroma melakukan semantic search
5. Hasil direrank dengan lexical heuristic
6. Jika hasil tidak cukup relevan, context dikosongkan

### 3. Embedding model dan vector store

File utama:

- [app/rag/client.py](../app/rag/client.py)

Yang dilakukan:

- Memanggil endpoint Ollama `/api/embeddings`
- Menyimpan dan mengambil embedding dari ChromaDB

### 4. Penyimpanan knowledge

File utama:

- [app/rag/ingest.py](../app/rag/ingest.py)

Yang dilakukan:

- Membaca dokumen dari folder knowledge
- Memecah dokumen menjadi chunk
- Menyimpan chunk, metadata, dan embedding ke ChromaDB

### 5. Penyusunan jawaban

File utama:

- [app/rag/generate.py](../app/rag/generate.py)

Yang dilakukan:

1. Membangun prompt ringan berisi riwayat percakapan, context knowledge perusahaan, dan pertanyaan user
2. Mengirim prompt ke Ollama chat model
3. Membiarkan Ollama menjawab secara natural dan singkat
4. Jika jawaban terpotong karena limit panjang, sistem mencoba melanjutkannya

### 6. Orkestrasi chat

File utama:

- [app/api/chat/service.py](../app/api/chat/service.py)
- [app/api/chat/repository.py](../app/api/chat/repository.py)

Yang dilakukan:

- Resolve atau membuat `conversation_id`
- Memuat dan menyimpan riwayat sesi ke SQLite
- Memanggil retrieval dan generator dengan history dari SQLite
- Mengembalikan `answer`, `citations`, dan `conversation_id`

## Bentuk Alur Saat Ini

```text
Pertanyaan user
-> resolve/create conversation_id
-> load recent history dari SQLite
-> simpan turn user
-> embedding query oleh Ollama
-> semantic search ke Chroma
-> rerank hasil retrieval
-> context knowledge perusahaan bila relevan
-> Ollama menyusun jawaban singkat dengan history
-> simpan turn assistant
-> API mengembalikan answer + citations + conversation_id
```
