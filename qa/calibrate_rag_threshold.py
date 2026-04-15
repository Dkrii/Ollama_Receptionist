import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from rag.client import embed_texts, get_collection
from rag.retrieve import (
    _build_semantic_query,
    _candidate_count,
    _items_are_semantically_relevant,
    _normalize_text,
    _semantic_rerank_items,
)


def load_testset(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Testset must be a JSON array.")
    return [item for item in payload if isinstance(item, dict)]


def parse_thresholds(raw_value: str) -> list[float]:
    values: list[float] = []
    for part in str(raw_value or "").split(","):
        candidate = part.strip()
        if not candidate:
            continue
        values.append(float(candidate))
    if not values:
        raise ValueError("At least one threshold is required.")
    return values


def collect_raw_items(query: str) -> list[dict[str, Any]]:
    collection = get_collection()
    retrieval_query = _build_semantic_query(query)
    query_vector = embed_texts([retrieval_query])[0]
    result = collection.query(
        query_embeddings=[query_vector],
        n_results=_candidate_count(collection),
        include=["documents", "metadatas", "distances"],
    )

    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    items: list[dict[str, Any]] = []
    for document, metadata, distance in zip(documents, metadatas, distances):
        content = _normalize_text(document)
        if not content:
            continue
        raw_distance = float(distance)
        items.append(
            {
                "content": content,
                "metadata": metadata or {},
                "distance": raw_distance,
                "score": round(1 / (1 + raw_distance), 6),
            }
        )
    return items


def evaluate_threshold(
    testset: list[dict[str, Any]],
    threshold: float,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []

    for item in testset:
        query_id = str(item.get("id") or "")
        label = str(item.get("label") or "").strip().lower()
        query = str(item.get("query") or "").strip()
        if not query:
            continue

        raw_items = collect_raw_items(query)
        filtered_items = [entry for entry in raw_items if float(entry["score"]) >= threshold]
        ranked_items = _semantic_rerank_items(query, filtered_items)
        returned = bool(ranked_items) and _items_are_semantically_relevant(ranked_items)

        top_raw = raw_items[0] if raw_items else {}
        top_ranked = ranked_items[0] if ranked_items else {}

        rows.append(
            {
                "id": query_id,
                "label": label,
                "query": query,
                "returned": returned,
                "raw_top_score": float(top_raw.get("score") or 0.0),
                "raw_bottom_score": float(raw_items[-1].get("score") or 0.0) if raw_items else 0.0,
                "filtered_count": len(filtered_items),
                "top_semantic_score": round(float(top_ranked.get("_semantic_score") or 0.0), 6),
                "top_combined_score": round(float(top_ranked.get("_combined_score") or 0.0), 6),
                "top_source": str((top_ranked.get("metadata") or {}).get("source") or ""),
                "top_chunk": (top_ranked.get("metadata") or {}).get("chunk_index"),
                "top_preview": str(top_ranked.get("content") or "")[:180],
            }
        )

    known_rows = [row for row in rows if row["label"] == "known"]
    unknown_rows = [row for row in rows if row["label"] == "unknown"]

    summary = {
        "threshold": threshold,
        "known_total": len(known_rows),
        "known_returned": sum(1 for row in known_rows if row["returned"]),
        "unknown_total": len(unknown_rows),
        "unknown_blocked": sum(1 for row in unknown_rows if not row["returned"]),
        "avg_filtered_known": round(
            statistics.mean(row["filtered_count"] for row in known_rows), 2
        ) if known_rows else 0.0,
        "avg_filtered_unknown": round(
            statistics.mean(row["filtered_count"] for row in unknown_rows), 2
        ) if unknown_rows else 0.0,
        "avg_top_raw_known": round(
            statistics.mean(row["raw_top_score"] for row in known_rows), 6
        ) if known_rows else 0.0,
        "avg_top_raw_unknown": round(
            statistics.mean(row["raw_top_score"] for row in unknown_rows), 6
        ) if unknown_rows else 0.0,
    }

    return {
        "summary": summary,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate RAG score thresholds against a labeled query set.")
    parser.add_argument("--testset", default="qa/testset-rag-threshold.json")
    parser.add_argument("--thresholds", default="0.12,0.35,0.55,0.70,0.72,0.74")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    started_at = time.perf_counter()
    testset = load_testset(Path(args.testset))
    thresholds = parse_thresholds(args.thresholds)

    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "testset": str(Path(args.testset)),
        "thresholds": thresholds,
        "results": [evaluate_threshold(testset, threshold) for threshold in thresholds],
        "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
    }

    output_path = str(args.output or "").strip()
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
