import requests
import chromadb
from chromadb.config import Settings as ChromaSettings
from functools import lru_cache

from config import settings


_http_session = requests.Session()


@lru_cache(maxsize=1)
def get_chroma_client() -> chromadb.HttpClient:
    return chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


@lru_cache(maxsize=1)
def get_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(name=settings.chroma_collection)


def embed_texts(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for text in texts:
        response = _http_session.post(
            f"{settings.ollama_base_url}/api/embeddings",
            json={"model": settings.ollama_embed_model, "prompt": text},
            timeout=90,
        )
        response.raise_for_status()
        vectors.append(response.json()["embedding"])
    return vectors
