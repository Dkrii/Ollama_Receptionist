import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings
from infrastructure.chroma import build_collection_metadata, get_chroma_client, get_collection
from modules.knowledge_base.ingest import ingest_knowledge
from modules.knowledge_base.documents import list_documents
from modules.knowledge_base.retrieve import retrieve_context


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def rebuild_collection(*, allow_empty_knowledge: bool = False) -> dict:
    client = get_chroma_client()
    metadata = build_collection_metadata()
    knowledge_dir = Path(settings.knowledge_dir)
    documents = list_documents(knowledge_dir)

    if not allow_empty_knowledge and not documents:
        raise RuntimeError(
            "Knowledge directory kosong. Rebuild dibatalkan untuk mencegah penghapusan index lama. "
            "Gunakan --allow-empty jika memang sengaja ingin reset collection kosong."
        )

    try:
        client.delete_collection(name=settings.chroma_collection)
        dropped = True
    except Exception:
        dropped = False

    client.get_or_create_collection(name=settings.chroma_collection, metadata=metadata)
    get_collection.cache_clear()

    ingestion_result = ingest_knowledge(Path(settings.knowledge_dir))

    return {
        "collection": settings.chroma_collection,
        "dropped_existing": dropped,
        "metadata": metadata,
        "ingestion": ingestion_result,
    }


def validate_retrieval(query: str) -> dict:
    result = retrieve_context(query)
    return {
        "query": query,
        "citations": len(result.get("citations") or []),
        "context_chars": len(result.get("context") or ""),
        "ok": bool((result.get("context") or "").strip() or (result.get("citations") or [])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild Chroma collection with explicit HNSW params and re-ingest knowledge.")
    parser.add_argument(
        "--validate-query",
        default="Jam operasional kantor?",
        help="Query for post-rebuild retrieval validation.",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Allow rebuild even when knowledge directory is empty.",
    )
    args = parser.parse_args()

    summary = rebuild_collection(allow_empty_knowledge=bool(args.allow_empty))
    validation = validate_retrieval(args.validate_query)

    _print_json({
        "rebuild": summary,
        "validation": validation,
    })

    return 0 if validation["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
