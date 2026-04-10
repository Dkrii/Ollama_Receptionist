from pydantic import BaseModel
from pathlib import Path
import os


class Settings(BaseModel):
    app_host: str = os.getenv("APP_HOST", "0.0.0.0")
    app_port: int = int(os.getenv("APP_PORT", "8000"))

    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
    ollama_chat_model: str = os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:3b")
    ollama_embed_model: str = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    ollama_num_predict: int = int(os.getenv("OLLAMA_NUM_PREDICT", "160"))
    ollama_num_predict_short: int = int(os.getenv("OLLAMA_NUM_PREDICT_SHORT", "96"))
    ollama_num_predict_long: int = int(os.getenv("OLLAMA_NUM_PREDICT_LONG", "320"))
    ollama_num_ctx: int = int(os.getenv("OLLAMA_NUM_CTX", "2048"))
    ollama_num_thread: int = int(os.getenv("OLLAMA_NUM_THREAD", "4"))

    chroma_host: str = os.getenv("CHROMA_HOST", "chroma")
    chroma_port: int = int(os.getenv("CHROMA_PORT", "8000"))
    chroma_collection: str = os.getenv("CHROMA_COLLECTION", "receptionist_kb")
    chroma_hnsw_m: int = int(os.getenv("CHROMA_HNSW_M", "32"))
    chroma_hnsw_construction_ef: int = int(os.getenv("CHROMA_HNSW_CONSTRUCTION_EF", "200"))
    chroma_hnsw_search_ef: int = int(os.getenv("CHROMA_HNSW_SEARCH_EF", "80"))
    chroma_hnsw_space: str = os.getenv("CHROMA_HNSW_SPACE", "cosine")

    rag_top_k: int = int(os.getenv("RAG_TOP_K", "2"))
    rag_score_threshold: float = float(os.getenv("RAG_SCORE_THRESHOLD", "0.0"))
    rag_chunk_size: int = int(os.getenv("RAG_CHUNK_SIZE", "900"))
    rag_chunk_overlap: int = int(os.getenv("RAG_CHUNK_OVERLAP", "150"))
    rag_max_context_chars: int = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "1600"))

    knowledge_dir: Path = Path(os.getenv("KNOWLEDGE_DIR", "/workspace/knowledge"))
    chat_db_path: Path = Path(os.getenv("CHAT_DB_PATH", "/workspace/runtime/chat.sqlite3"))
    chat_session_idle_minutes: int = int(os.getenv("CHAT_SESSION_IDLE_MINUTES", "5"))
    chat_recent_turns: int = int(os.getenv("CHAT_RECENT_TURNS", "6"))
    chat_history_max_chars: int = int(os.getenv("CHAT_HISTORY_MAX_CHARS", "1000"))
    chat_transcript_retention_days: int = int(os.getenv("CHAT_TRANSCRIPT_RETENTION_DAYS", "7"))
    chat_intent_max_retries: int = int(os.getenv("CHAT_INTENT_MAX_RETRIES", "2"))
    chat_natural_response_enabled: bool = os.getenv("CHAT_NATURAL_RESPONSE_ENABLED", "1") in {
        "1",
        "true",
        "yes",
        "on",
    }


settings = Settings()
