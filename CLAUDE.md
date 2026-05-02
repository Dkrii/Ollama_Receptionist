# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

A **Virtual Receptionist Kiosk** — an AI-powered web application where visitors ask questions via a chat UI. The system answers using RAG over a knowledge base and routes contact requests to employees via a state-machine contact flow. It ships as a Docker Compose stack.

Respect .gitignore. don't read the file and folder in gitignore

## Running the App

```bash
docker compose up -d          # Start app + ChromaDB
docker compose stop           # Stop
docker compose logs -f app    # Stream app logs
```

App is served at `http://localhost:8000`. The `knowledge/` directory is volume-mounted; documents placed there are ingested on startup or via reindex.

## Key Endpoints (Development)

| Path                    | Purpose                             |
| ----------------------- | ----------------------------------- |
| `/`                     | Kiosk UI (visitor-facing)           |
| `/dev`                  | Dev/testing chat interface          |
| `/admin`                | Admin panel (knowledge + employees) |
| `POST /api/chat`        | Non-streaming chat                  |
| `POST /api/chat/stream` | NDJSON streaming chat               |
| `POST /api/reindex`     | Rebuild ChromaDB from `knowledge/`  |
| `GET /health`           | Liveness check                      |

## Rebuild ChromaDB manually (inside container)

```bash
docker compose exec app python scripts/rebuild_chroma_collection.py
docker compose exec app python scripts/rebuild_chroma_collection.py --validate-query "your test query"
```

## Architecture

```
Browser (kiosk / dev / admin)
    ↓ HTTP
FastAPI  (app/main.py)
    ├── Chat routes       app/api/chat/routes.py
    ├── Admin routes      app/api/admin/routes.py
    └── Web routes        app/api/web/routes.py
         ↓
    Service layer
    ├── ChatAppService    app/api/chat/service.py   — orchestrates every chat turn
    ├── AdminAppService   app/api/admin/service.py  — knowledge management
    └── WebPageService    app/api/web/service.py
         ↓`
    Business logic
    ├── Intent detection  app/api/chat/intent.py    — contact vs. info intent
    ├── Contact flow      app/api/chat/service.py   — state machine (await_disambiguation → confirmation → …)
    └── RAG pipeline      app/rag/
         ├── retrieve.py  — ChromaDB semantic search + lexical reranking
         ├── generate.py  — Ollama/OpenRouter answer generation
         └── ingest.py    — chunk + embed documents into ChromaDB
         ↓
    External services`
    ├── Ollama / OpenRouter   LLM + embeddings (controlled by AI_PROVIDER)
    ├── ChromaDB              vector store (Docker service)
    └── SQLite                conversation history  (runtime/chat.sqlite3)
```

### Request flow (chat turn)

1. `POST /api/chat` → `ChatAppService.handle_chat()`
2. Conversation resolved / created in SQLite via `ChatRepository`
3. Recent history loaded (`CHAT_RECENT_TURNS`, default 4 turns)
4. Intent detected (`intent.py`) — if contact intent, delegate to contact-flow branch
5. RAG: retrieve top-K chunks from ChromaDB, rerank, threshold at `RAG_SCORE_THRESHOLD` (0.72)
6. `ai_client.py` calls Ollama or OpenRouter with assembled prompt + context
7. Response saved to SQLite, returned with `conversation_id`

### Contact flow states

`await_disambiguation` → `await_confirmation` → `contacting_unavailable_pending` → `await_unavailable_choice` → `await_waiter_name` / `await_message_name` / `await_message_goal`

Implemented as a `flow_state` dict threaded through `ChatAppService`.

## Configuration

All tunables live in `.env` (see `.env.example`). `AI_PROVIDER` is the single switch that controls **both** chat and embedding.

**OpenRouter mode:**
```env
AI_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_CHAT_MODEL=openai/gpt-4o-mini
OPENROUTER_EMBED_MODEL=openai/text-embedding-3-small  # default jika tidak diset
```

**Ollama mode (default):**
```env
AI_PROVIDER=ollama
OLLAMA_CHAT_MODEL=qwen2.5:3b
OLLAMA_EMBED_MODEL=nomic-embed-text
```

| Variable              | Default            | Effect                                        |
| --------------------- | ------------------ | --------------------------------------------- |
| `AI_PROVIDER`         | `ollama`           | `ollama` or `openrouter` — controls chat + embedding |
| `RAG_SCORE_THRESHOLD` | `0.72`             | Min cosine similarity to use context          |
| `RAG_TOP_K`           | `2`                | Chunks retrieved per query                    |
| `RAG_CHUNK_SIZE`      | `900`              | Characters per chunk                          |
| `CHAT_RECENT_TURNS`   | `4`                | History turns sent to LLM                     |

Settings are loaded via Pydantic in `app/config.py` and injected as a singleton through FastAPI's lifespan.

## Code Conventions

- **Repository pattern**: data access is isolated in `repository.py` files; services call repositories, not raw DB/HTTP clients.
- **Dependency injection via lifespan**: services and clients are constructed once in `app/main.py`'s lifespan context and injected into routes.
- **AI client abstraction**: `app/ai_client.py` wraps both Ollama and OpenRouter behind a single interface; switch providers via `AI_PROVIDER` env var.
- **Streaming**: `/api/chat/stream` returns NDJSON; generation functions in `app/rag/generate.py` have paired sync/stream variants.
- **No test suite**: test secara manual via `/dev` interface atau `POST /api/chat`.

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
