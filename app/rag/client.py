import requests
import chromadb
from chromadb.config import Settings as ChromaSettings
from functools import lru_cache

from ai_client import embed_text
from config import settings


_http_session = requests.Session()


@lru_cache(maxsize=1)
def get_chroma_client() -> chromadb.HttpClient:
    return chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def build_collection_metadata() -> dict:
    return {
        "hnsw:space": settings.chroma_hnsw_space,
        "hnsw:M": int(settings.chroma_hnsw_m),
        "hnsw:construction_ef": int(settings.chroma_hnsw_construction_ef),
        "hnsw:search_ef": int(settings.chroma_hnsw_search_ef),
    }


@lru_cache(maxsize=1)
def get_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=settings.chroma_collection,
        metadata=build_collection_metadata(),
    )


def embed_texts(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for text in texts:
        vectors.append(list(_embed_text_cached((text or "").strip())))
    return vectors


@lru_cache(maxsize=256)
def _embed_text_cached(text: str) -> tuple[float, ...]:
    embedding = embed_text(text, timeout=90)
    return tuple(float(value) for value in embedding)
