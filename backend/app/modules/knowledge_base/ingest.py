from pathlib import Path
from typing import Dict

from config import settings
from modules.knowledge_base.chroma import get_collection, embed_texts
from modules.knowledge_base.documents import list_documents, read_document, build_chunks


def ingest_knowledge(knowledge_dir: Path | None = None) -> Dict:
    target_dir = knowledge_dir or settings.knowledge_dir
    collection = get_collection()

    existing = collection.get(include=[])
    existing_ids = existing.get("ids", [])
    if existing_ids:
        collection.delete(ids=existing_ids)

    documents = list_documents(target_dir)
    total_chunks = 0

    for file_path in documents:
        text = read_document(file_path)
        records = build_chunks(
            file_path,
            text,
            chunk_size=settings.rag_chunk_size,
            overlap=settings.rag_chunk_overlap,
        )

        if not records:
            continue

        contents = [item["content"] for item in records]
        vectors = embed_texts(contents)

        collection.add(
            ids=[item["id"] for item in records],
            documents=contents,
            embeddings=vectors,
            metadatas=[item["metadata"] for item in records],
        )

        total_chunks += len(records)

    return {
        "documents": len(documents),
        "chunks": total_chunks,
        "collection": settings.chroma_collection,
        "knowledge_dir": str(target_dir),
    }
