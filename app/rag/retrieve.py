from typing import Dict, List

from config import settings
from rag.client import get_collection, embed_texts


def retrieve_context(query: str) -> Dict:
    collection = get_collection()
    query_vector = embed_texts([query])[0]

    result = collection.query(
        query_embeddings=[query_vector],
        n_results=settings.rag_top_k,
        include=["documents", "metadatas", "distances"],
    )

    documents: List[str] = result.get("documents", [[]])[0]
    metadatas: List[dict] = result.get("metadatas", [[]])[0]
    distances: List[float] = result.get("distances", [[]])[0]

    items = []
    for doc, meta, distance in zip(documents, metadatas, distances):
        score = 1 / (1 + distance)
        if score < settings.rag_score_threshold:
            continue
        items.append(
            {
                "content": doc,
                "metadata": meta,
                "score": round(score, 4),
            }
        )

    context = "\n\n".join(item["content"] for item in items)
    context = context[: settings.rag_max_context_chars]

    return {
        "context": context,
        "citations": items,
    }
