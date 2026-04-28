from pydantic import BaseModel
from pathlib import Path
import os


def _frontend_src_dir() -> Path:
    configured = os.getenv("FRONTEND_SRC_DIR")
    if configured:
        return Path(configured)

    app_dir = Path(__file__).resolve().parent
    if app_dir.parent.name == "backend":
        return app_dir.parent.parent / "frontend" / "src"
    return Path("/frontend/src")


class Settings(BaseModel):
    app_env: str = os.getenv("APP_ENV", "development").strip().lower()
    app_url: str = os.getenv("APP_URL", "").strip().rstrip("/")
    contact_call_provider: str = os.getenv("CONTACT_CALL_PROVIDER", "twilio").strip().lower()
    contact_messaging_provider: str = os.getenv("CONTACT_MESSAGING_PROVIDER", "wablas").strip().lower()

    ai_provider: str = os.getenv("AI_PROVIDER", "ollama").strip().lower()

    openrouter_base_url: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip()
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "").strip()
    openrouter_chat_model: str = os.getenv("OPENROUTER_CHAT_MODEL", "").strip()
    openrouter_embed_model: str = os.getenv("OPENROUTER_EMBED_MODEL", "openai/text-embedding-3-small").strip()
    openrouter_site_name: str = os.getenv("OPENROUTER_SITE_NAME", "").strip()

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
    rag_score_threshold: float = float(os.getenv("RAG_SCORE_THRESHOLD", "0.72"))
    rag_chunk_size: int = int(os.getenv("RAG_CHUNK_SIZE", "900"))
    rag_chunk_overlap: int = int(os.getenv("RAG_CHUNK_OVERLAP", "150"))
    rag_max_context_chars: int = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "1600"))

    knowledge_dir: Path = Path(os.getenv("KNOWLEDGE_DIR", "/workspace/knowledge"))
    frontend_src_dir: Path = _frontend_src_dir()
    chat_db_path: Path = Path(os.getenv("CHAT_DB_PATH", "/workspace/runtime/chat.sqlite3"))
    chat_session_idle_minutes: int = int(os.getenv("CHAT_SESSION_IDLE_MINUTES", "5"))
    chat_recent_turns: int = int(os.getenv("CHAT_RECENT_TURNS", "6"))
    chat_history_max_chars: int = int(os.getenv("CHAT_HISTORY_MAX_CHARS", "1000"))
    chat_transcript_retention_days: int = int(os.getenv("CHAT_TRANSCRIPT_RETENTION_DAYS", "7"))
    chat_intent_max_retries: int = int(os.getenv("CHAT_INTENT_MAX_RETRIES", "2"))
    chat_intent_timeout_seconds: int = int(os.getenv("CHAT_INTENT_TIMEOUT_SECONDS", "20"))
    chat_natural_response_enabled: bool = os.getenv("CHAT_NATURAL_RESPONSE_ENABLED", "1") in {
        "1",
        "true",
        "yes",
        "on",
    }
    twilio_account_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    twilio_api_key_sid: str = os.getenv("TWILIO_API_KEY_SID", "").strip()
    twilio_api_key_secret: str = os.getenv("TWILIO_API_KEY_SECRET", "").strip()
    twilio_twiml_app_sid: str = os.getenv("TWILIO_TWIML_APP_SID", "").strip()
    contact_call_from_number: str = os.getenv("CONTACT_CALL_FROM_NUMBER", "").strip()
    telnyx_api_base_url: str = os.getenv("TELNYX_API_BASE_URL", "https://api.telnyx.com").strip().rstrip("/")
    telnyx_api_key: str = os.getenv("TELNYX_API_KEY", "").strip()
    telnyx_telephony_credential_id: str = os.getenv("TELNYX_TELEPHONY_CREDENTIAL_ID", "").strip()
    telnyx_caller_id_number: str = os.getenv("TELNYX_CALLER_ID_NUMBER", "").strip()
    telnyx_timeout_seconds: int = int(os.getenv("TELNYX_TIMEOUT_SECONDS", "15"))
    wablas_base_url: str = os.getenv("WABLAS_BASE_URL", "https://wablas.com").strip().rstrip("/")
    wablas_token: str = os.getenv("WABLAS_TOKEN", "").strip()
    wablas_secret_key: str = os.getenv("WABLAS_SECRET_KEY", "").strip()
    wablas_timeout_seconds: int = int(os.getenv("WABLAS_TIMEOUT_SECONDS", "15"))
    wablas_retry_attempts: int = int(os.getenv("WABLAS_RETRY_ATTEMPTS", "3"))
    wablas_retry_backoff_seconds: float = float(os.getenv("WABLAS_RETRY_BACKOFF_SECONDS", "0.4"))
    wablas_test_group_id: str = os.getenv("WABLAS_TEST_GROUP_ID", "").strip()


settings = Settings()
