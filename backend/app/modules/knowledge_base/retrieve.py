import logging
import math
import re
import time
from typing import Dict, List

from config import settings
from infrastructure.chroma import get_collection, embed_texts
from shared.text import normalize_text


_logger = logging.getLogger(__name__)
_collection_count_cache: dict[str, float | int] = {
    "value": 0,
    "expires_at": 0.0,
}

_SEMANTIC_PREVIEW_MAX_CHARS = 1400
_SEMANTIC_WEIGHT = 0.5
_LEXICAL_WEIGHT = 0.35
_VECTOR_WEIGHT = 0.15
_SEMANTIC_HISTORY_CHARS = 320
_SNIPPET_MAX_CHARS = 420
_VECTOR_SCORE_MARGIN = 0.05
_QUERY_STOPWORDS = {
    "a",
    "ada",
    "adalah",
    "agar",
    "apa",
    "apakah",
    "atau",
    "bagaimana",
    "bahwa",
    "bagi",
    "bisa",
    "buat",
    "dalam",
    "dan",
    "dari",
    "dengan",
    "di",
    "dimana",
    "di mana",
    "hari",
    "itu",
    "ini",
    "jadi",
    "jika",
    "kalau",
    "kami",
    "kamu",
    "ke",
    "keadaan",
    "kerja",
    "lebih",
    "mau",
    "mohon",
    "pada",
    "para",
    "saja",
    "saya",
    "sebagai",
    "sebutkan",
    "sedang",
    "sekarang",
    "sih",
    "silakan",
    "tentang",
    "the",
    "to",
    "tolong",
    "untuk",
    "yang",
}


def _semantic_preview(text: str) -> str:
    normalized = normalize_text(text)
    if not normalized:
        return ""
    return normalized[:_SEMANTIC_PREVIEW_MAX_CHARS]


def _tokenize(text: str) -> list[str]:
    normalized = normalize_text(text).lower()
    if not normalized:
        return []

    raw_tokens = re.findall(r"[a-z0-9]+", normalized)
    return [token for token in raw_tokens if len(token) > 1]


def _informative_query_tokens(text: str) -> list[str]:
    return [token for token in _tokenize(text) if token not in _QUERY_STOPWORDS]


def _query_bigrams(tokens: list[str]) -> set[str]:
    return {
        f"{left} {right}"
        for left, right in zip(tokens, tokens[1:])
        if left and right
    }


def _query_token_coverage(query: str, content: str) -> float:
    query_tokens = _informative_query_tokens(query)
    if not query_tokens:
        return 0.0

    content_tokens = set(_tokenize(content))
    if not content_tokens:
        return 0.0

    overlap = sum(1 for token in query_tokens if token in content_tokens)
    return overlap / max(1, len(query_tokens))


def _lexical_overlap_score(query: str, content: str) -> float:
    query_tokens = _informative_query_tokens(query)
    if not query_tokens:
        return 0.0

    content_tokens = set(_tokenize(content))
    if not content_tokens:
        return 0.0

    unigram_score = _query_token_coverage(query, content)

    normalized_content = normalize_text(content).lower()
    bigrams = _query_bigrams(query_tokens)
    bigram_hits = sum(1 for gram in bigrams if gram in normalized_content)
    bigram_score = bigram_hits / max(1, len(bigrams)) if bigrams else 0.0

    longest_token = max(query_tokens, key=len, default="")
    longest_bonus = 0.12 if longest_token and longest_token in normalized_content else 0.0
    whole_query_bonus = 0.1 if normalize_text(query).lower() in normalized_content else 0.0

    return min(1.0, (unigram_score * 0.72) + (bigram_score * 0.16) + longest_bonus + whole_query_bonus)


def _query_bigram_coverage(query: str, content: str) -> float:
    query_tokens = _informative_query_tokens(query)
    bigrams = _query_bigrams(query_tokens)
    if not bigrams:
        return 0.0

    normalized_content = normalize_text(content).lower()
    hits = sum(1 for gram in bigrams if gram in normalized_content)
    return hits / max(1, len(bigrams))


def _slice_on_word_boundaries(text: str, start: int, width: int) -> str:
    normalized = normalize_text(text)
    if not normalized:
        return ""

    start = max(0, min(start, max(0, len(normalized) - 1)))
    end = min(len(normalized), start + width)

    while start > 0 and normalized[start - 1].isalnum():
        start -= 1
    while end < len(normalized) and normalized[end - 1].isalnum():
        end += 1

    return normalized[start:end].strip(" ,;:")


def _segment_content(content: str) -> list[str]:
    raw_text = str(content or "").strip()
    raw_text = re.sub(
        r"\s+(?=[A-Z][A-Za-z0-9/&().,' -]{1,40}\s+\|)",
        "\n",
        raw_text,
    )
    raw_text = re.sub(
        r"\s+(?=[A-Z][^|?]{1,120}\?\s+\|)",
        "\n",
        raw_text,
    )
    raw_segments = re.split(r"(?:\n+|(?<=[.?!])\s+)", raw_text)
    segments = [normalize_text(segment) for segment in raw_segments]
    return [segment for segment in segments if segment]


def _build_focus_snippet(content: str, query: str) -> str:
    segments = _segment_content(content)
    if not segments:
        return ""

    normalized = " ".join(segments).strip()
    if len(normalized) <= _SNIPPET_MAX_CHARS:
        return normalized

    best_index = 0
    best_score = -1.0
    for index, segment in enumerate(segments):
        score = _lexical_overlap_score(query, segment)
        if score > best_score:
            best_index = index
            best_score = score

    snippet_parts = [segments[best_index]]
    left = best_index - 1
    right = best_index + 1

    while left >= 0 or right < len(segments):
        added = False

        if right < len(segments):
            candidate = " ".join(snippet_parts + [segments[right]])
            if len(candidate) <= _SNIPPET_MAX_CHARS:
                snippet_parts.append(segments[right])
                right += 1
                added = True

        if left >= 0:
            candidate = " ".join([segments[left], *snippet_parts])
            if len(candidate) <= _SNIPPET_MAX_CHARS:
                snippet_parts.insert(0, segments[left])
                left -= 1
                added = True

        if not added:
            break

    snippet = " ".join(snippet_parts).strip()
    if left >= 0:
        snippet = f"... {snippet}"
    if right < len(segments):
        snippet = snippet.rstrip(".")
        snippet = f"{snippet} ..."
    return snippet


def _build_semantic_query(query: str, history: list[dict] | None = None) -> str:
    current_query = normalize_text(query)
    if not current_query or not history:
        return current_query

    recent_lines: list[str] = []
    total_chars = 0
    for item in reversed(history[-4:]):
        content = normalize_text(str(item.get("content") or ""))
        if not content or content == current_query:
            continue

        role = str(item.get("role") or "").strip().lower()
        prefix = "Pengguna" if role == "user" else "Asisten"
        line = f"{prefix}: {content}"
        if total_chars + len(line) > _SEMANTIC_HISTORY_CHARS:
            break
        recent_lines.insert(0, line)
        total_chars += len(line)

    if not recent_lines:
        return current_query

    return f"Pertanyaan saat ini: {current_query}\nKonteks percakapan terbaru:\n" + "\n".join(recent_lines)


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0

    dot_product = 0.0
    left_norm = 0.0
    right_norm = 0.0

    for left_value, right_value in zip(left, right):
        dot_product += left_value * right_value
        left_norm += left_value * left_value
        right_norm += right_value * right_value

    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0

    return dot_product / (math.sqrt(left_norm) * math.sqrt(right_norm))


def _candidate_count(collection) -> int:
    desired = max(settings.rag_top_k * 6, 12)
    now = time.monotonic()
    cached_value = int(_collection_count_cache.get("value") or 0)
    cached_expiry = float(_collection_count_cache.get("expires_at") or 0.0)

    if cached_value > 0 and cached_expiry > now:
        total = max(settings.rag_top_k, cached_value)
        if total <= 64:
            return total
        return min(desired, total)

    try:
        total = max(settings.rag_top_k, collection.count())
        _collection_count_cache["value"] = int(total)
        _collection_count_cache["expires_at"] = now + 45.0
        if total <= 64:
            return total
        return min(desired, total)
    except Exception:
        return desired


def _semantic_rerank_items(query: str, items: list[dict]) -> list[dict]:
    if not items:
        return []

    preview_texts = [_semantic_preview(item.get("content", "")) for item in items]
    query_text = normalize_text(query)

    try:
        vectors = embed_texts([query_text, *preview_texts])
    except Exception:
        _logger.exception("knowledge.retrieve semantic rerank failed query=%s", query_text)
        return items

    if len(vectors) != len(items) + 1:
        return items

    query_vector = vectors[0]
    ranked_items: list[dict] = []
    for item, item_vector in zip(items, vectors[1:]):
        semantic_score = _cosine_similarity(query_vector, item_vector)
        content_text = str(item.get("content") or "")
        lexical_score = _lexical_overlap_score(query_text, content_text)
        token_coverage = _query_token_coverage(query_text, content_text)
        bigram_coverage = _query_bigram_coverage(query_text, content_text)
        combined_score = (
            (semantic_score * _SEMANTIC_WEIGHT)
            + (lexical_score * _LEXICAL_WEIGHT)
            + (float(item.get("score") or 0.0) * _VECTOR_WEIGHT)
        )
        ranked_items.append(
            {
                **item,
                "_semantic_score": round(semantic_score, 6),
                "_lexical_score": round(lexical_score, 6),
                "_token_coverage": round(token_coverage, 6),
                "_bigram_coverage": round(bigram_coverage, 6),
                "_combined_score": round(combined_score, 6),
            }
        )

    ranked_items.sort(
        key=lambda item: (
            item.get("_combined_score", 0.0),
            item.get("_lexical_score", 0.0),
            item.get("_semantic_score", 0.0),
            item.get("score", 0.0),
        ),
        reverse=True,
    )
    return ranked_items


def _items_are_semantically_relevant(items: list[dict]) -> bool:
    if not items:
        return False

    semantic_scores = [float(item.get("_semantic_score", 0.0)) for item in items[:4]]
    combined_scores = [float(item.get("_combined_score", 0.0)) for item in items[:4]]
    lexical_scores = [float(item.get("_lexical_score", 0.0)) for item in items[:4]]
    token_coverages = [float(item.get("_token_coverage", 0.0)) for item in items[:4]]
    bigram_coverages = [float(item.get("_bigram_coverage", 0.0)) for item in items[:4]]

    top_semantic = semantic_scores[0]
    top_combined = combined_scores[0]
    top_lexical = lexical_scores[0]
    top_coverage = token_coverages[0]
    top_bigram_coverage = bigram_coverages[0]
    second_semantic = semantic_scores[1] if len(semantic_scores) > 1 else -1.0
    recent_average = sum(semantic_scores) / len(semantic_scores)

    if top_bigram_coverage >= 0.5:
        return True
    if top_coverage >= 0.66:
        return True
    if top_lexical >= 0.5:
        return True
    if top_lexical >= 0.34 and top_combined >= 0.28:
        return True
    if top_semantic >= 0.24:
        return True
    if top_semantic >= 0.19 and top_combined >= 0.30:
        return True
    if top_semantic >= 0.17 and (top_semantic - second_semantic) >= 0.04:
        return True
    if top_semantic >= 0.16 and (top_semantic - recent_average) >= 0.03:
        return True
    return False


def _strip_semantic_metadata(items: list[dict]) -> list[dict]:
    cleaned: list[dict] = []
    for item in items:
        cleaned.append(
            {
                key: value
                for key, value in item.items()
                if key not in {"_semantic_score", "_lexical_score", "_token_coverage", "_bigram_coverage", "_combined_score"}
            }
        )
    return cleaned


def retrieve_context(query: str, history: list[dict] | None = None) -> Dict:
    retrieval_query = _build_semantic_query(query, history)
    try:
        collection = get_collection()
        query_vector = embed_texts([retrieval_query])[0]

        result = collection.query(
            query_embeddings=[query_vector],
            n_results=_candidate_count(collection),
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        _logger.exception("knowledge.retrieve failed query=%s", retrieval_query)
        return {
            "context": "",
            "citations": [],
        }

    documents: List[str] = (result.get("documents") or [[]])[0]
    metadatas: List[dict] = (result.get("metadatas") or [[]])[0]
    distances: List[float] = (result.get("distances") or [[]])[0]

    items = []
    for doc, meta, distance in zip(documents, metadatas, distances):
        content = normalize_text(doc)
        if not content:
            continue

        score = 1 / (1 + distance)

        items.append(
            {
                "content": content,
                "metadata": meta,
                "score": round(score, 4),
            }
        )

    ranked_items = _semantic_rerank_items(retrieval_query, items)
    if ranked_items and not _items_are_semantically_relevant(ranked_items):
        return {
            "context": "",
            "citations": [],
            "support": {
                "top_semantic": 0.0,
                "top_lexical": 0.0,
                "top_coverage": 0.0,
                "top_combined": 0.0,
                "grounding": "low",
            },
        }

    top_lexical = float(ranked_items[0].get("_lexical_score", 0.0)) if ranked_items else 0.0
    top_coverage = float(ranked_items[0].get("_token_coverage", 0.0)) if ranked_items else 0.0
    top_bigram_coverage = float(ranked_items[0].get("_bigram_coverage", 0.0)) if ranked_items else 0.0
    top_combined = float(ranked_items[0].get("_combined_score", 0.0)) if ranked_items else 0.0
    second_lexical = float(ranked_items[1].get("_lexical_score", 0.0)) if len(ranked_items) > 1 else 0.0

    max_items = settings.rag_top_k
    if top_lexical >= 0.9:
        max_items = 1
    elif top_lexical >= 0.55 and (top_lexical - second_lexical) >= 0.04:
        max_items = 1

    raw_top_items = ranked_items[:max_items]
    top_items = _strip_semantic_metadata(raw_top_items)

    snippet_parts: list[str] = []
    used_chars = 0
    for item in raw_top_items:
        snippet = _build_focus_snippet(str(item.get("content") or ""), retrieval_query)
        if not snippet:
            continue

        projected = used_chars + len(snippet) + (2 if snippet_parts else 0)
        if snippet_parts and projected > settings.rag_max_context_chars:
            break

        if not snippet_parts and len(snippet) > settings.rag_max_context_chars:
            snippet = _slice_on_word_boundaries(snippet, 0, settings.rag_max_context_chars)

        snippet_parts.append(snippet)
        used_chars += len(snippet) + (2 if len(snippet_parts) > 1 else 0)

    context = "\n\n".join(snippet_parts).strip()
    top_semantic = float(ranked_items[0].get("_semantic_score", 0.0)) if ranked_items else 0.0

    grounding = "low"
    if top_coverage >= 0.66 and (top_lexical >= 0.55 or top_combined >= 0.64):
        grounding = "high"
    elif top_coverage >= 0.4 or top_lexical >= 0.3 or top_combined >= 0.5:
        grounding = "medium"

    return {
        "context": context,
        "citations": top_items,
        "support": {
            "top_semantic": round(top_semantic, 6),
            "top_lexical": round(top_lexical, 6),
            "top_coverage": round(top_coverage, 6),
            "top_bigram_coverage": round(top_bigram_coverage, 6),
            "top_combined": round(top_combined, 6),
            "grounding": grounding,
        },
    }
