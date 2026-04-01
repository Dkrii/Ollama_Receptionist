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
    ollama_num_ctx: int = int(os.getenv("OLLAMA_NUM_CTX", "2048"))
    ollama_num_thread: int = int(os.getenv("OLLAMA_NUM_THREAD", "4"))
    social_cache_ttl_seconds: int = int(os.getenv("SOCIAL_CACHE_TTL_SECONDS", "900"))

    chroma_host: str = os.getenv("CHROMA_HOST", "chroma")
    chroma_port: int = int(os.getenv("CHROMA_PORT", "8000"))
    chroma_collection: str = os.getenv("CHROMA_COLLECTION", "receptionist_kb")

    rag_top_k: int = int(os.getenv("RAG_TOP_K", "3"))
    rag_score_threshold: float = float(os.getenv("RAG_SCORE_THRESHOLD", "0.0"))
    rag_chunk_size: int = int(os.getenv("RAG_CHUNK_SIZE", "900"))
    rag_chunk_overlap: int = int(os.getenv("RAG_CHUNK_OVERLAP", "150"))
    rag_max_context_chars: int = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "3200"))
    rag_strict_mode: bool = os.getenv("RAG_STRICT_MODE", "true").lower() in {"1", "true", "yes"}
    rag_fallback_policy: str = os.getenv("RAG_FALLBACK_POLICY", "context_only")

    knowledge_dir: Path = Path(os.getenv("KNOWLEDGE_DIR", "/workspace/knowledge"))


settings = Settings()
