import re
import logging
from typing import Dict, List

from config import settings
from rag.client import get_collection, embed_texts


_logger = logging.getLogger(__name__)


STOPWORDS = {
    "yang", "dan", "atau", "untuk", "dengan", "pada", "dari", "ke", "di", "ini", "itu",
    "the", "and", "for", "from", "with", "that", "have", "has", "are", "was", "were",
    "anda", "saya", "kami", "mereka", "kamu", "apa", "siapa", "berapa", "kapan", "dimana",
}

IMPORTANT_SHORT_TOKENS = {"jam", "hrd", "it", "she", "qcc", "ojt", "k3"}
LOCATION_TOKENS = {"dimana", "lokasi", "letak", "berada", "sebelah", "lantai", "ruang", "area", "gedung", "mana"}
GUIDANCE_MARKERS = (
    "panduan respons",
    "topik pertanyaan | cara merespons",
    "jawab berdasarkan bab",
    "ketika tidak memiliki informasi",
    "prinsip dasar",
)
PROFILE_MARKERS = (
    "profil",
    "perusahaan",
    "sejarah",
    "visi",
    "misi",
    "nilai",
    "segmen",
    "standar kualitas",
    "pt akebono",
    "akebono brake astra indonesia",
)
LAYOUT_MARKERS = (
    "layout",
    "fasilitas gedung",
    "gambaran umum gedung",
    "zona produksi",
    "toilet",
    "mushola",
    "parkir",
    "lobi",
    "lantai",
)
FOLLOW_UP_MARKERS = (
    "itu",
    "tadi",
    "yang tadi",
    "kalau yang",
    "lantai berapa",
    "jam berapa",
)


def _normalize_tokens(text: str) -> list[str]:
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", (text or "").lower())
    return [
        token
        for token in cleaned.split()
        if (len(token) >= 4 or token in IMPORTANT_SHORT_TOKENS) and token not in STOPWORDS
    ]


def _message_tokens(text: str) -> list[str]:
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", (text or "").lower())
    return [token for token in cleaned.split() if token]


def _last_user_turn(history: list[dict] | None) -> str:
    for item in reversed(history or []):
        if str(item.get("role", "")).lower() != "user":
            continue
        content = str(item.get("content", "")).strip()
        if content:
            return content
    return ""


def _is_follow_up_query(query: str) -> bool:
    lowered = " ".join((query or "").lower().split())
    if any(marker in lowered for marker in FOLLOW_UP_MARKERS):
        return True
    return len(_message_tokens(lowered)) <= 6


def _build_retrieval_query(query: str, history: list[dict] | None = None) -> str:
    previous_user_turn = _last_user_turn(history)
    if not previous_user_turn:
        return query
    if not _is_follow_up_query(query):
        return query
    return f"{previous_user_turn}\n{query}"


def _query_terms(query: str) -> list[str]:
    tokens = _normalize_tokens(query)
    if not tokens:
        return []

    expanded = set(tokens)
    aliases = {
        "operasional": {"operasional", "kerja", "aktivitas"},
        "kerja": {"kerja", "operasional", "jam"},
        "profil": {"profil", "perusahaan", "identitas", "sejarah", "visi", "misi", "nilai"},
        "perusahaan": {"perusahaan", "profil", "identitas", "sejarah", "visi", "misi", "nilai"},
        "visi": {"visi", "misi"},
        "misi": {"visi", "misi"},
        "evakuasi": {"evakuasi", "darurat", "muster"},
        "muster": {"muster", "evakuasi", "darurat"},
    }
    for token in tokens:
        expanded.update(aliases.get(token, {token}))

    return list(expanded)


def _query_focus_tokens(query: str) -> list[str]:
    return [token for token in _normalize_tokens(query) if token not in LOCATION_TOKENS]


def _structured_subject_boost(query: str, content: str) -> tuple[int, int]:
    focus_tokens = _query_focus_tokens(query)
    if not focus_tokens:
        return 0, 0

    focus_phrase = " ".join(focus_tokens).strip().lower()
    best_exact = 0
    best_prefix = 0

    for raw_line in (content or "").splitlines():
        if "|" not in raw_line:
            continue

        subject = raw_line.split("|", 1)[0].strip().lower()
        subject_tokens = set(_normalize_tokens(subject))

        if subject == focus_phrase:
            best_exact = 1
        if focus_phrase and subject.startswith(focus_phrase):
            best_prefix = 1
        if subject_tokens == set(focus_tokens):
            best_exact = 1

    return best_exact, best_prefix


def _lexical_metrics(query: str, content: str) -> tuple[int, float, int]:
    query_terms = _query_terms(query)
    if not query_terms:
        return 0, 0.0, 0

    content_lower = (content or "").lower()
    heading_window = content_lower[:220]
    content_tokens = set(_normalize_tokens(content_lower))
    heading_tokens = set(_normalize_tokens(heading_window))
    matched_terms = [term for term in query_terms if term in content_tokens]
    heading_matches = sum(1 for term in query_terms if term in heading_tokens)
    coverage = len(set(matched_terms)) / len(set(query_terms))
    return len(set(matched_terms)), coverage, heading_matches


def _is_guidance_chunk(content: str) -> bool:
    lowered = (content or "").lower()
    return any(marker in lowered for marker in GUIDANCE_MARKERS)


def _is_profile_query(query: str) -> bool:
    lowered = (query or "").lower()
    return any(marker in lowered for marker in PROFILE_MARKERS)


def _is_layout_chunk(content: str) -> bool:
    lowered = (content or "").lower()
    return any(marker in lowered for marker in LAYOUT_MARKERS)


def _items_are_relevant(query: str, items: list[dict]) -> bool:
    query_terms = _query_terms(query)
    if not query_terms:
        return False

    best_match_count = 0
    best_coverage = 0.0
    for item in items:
        match_count, coverage, _ = _lexical_metrics(query, item.get("content", ""))
        best_match_count = max(best_match_count, match_count)
        best_coverage = max(best_coverage, coverage)

    if best_match_count >= 2:
        return True
    return best_coverage >= 0.2


def _candidate_count(collection) -> int:
    desired = max(settings.rag_top_k * 6, 12)
    try:
        total = max(settings.rag_top_k, collection.count())
        if total <= 64:
            return total
        return min(desired, total)
    except Exception:
        return desired


def _rerank_items(query: str, items: list[dict]) -> list[dict]:
    prefer_profile_chunks = _is_profile_query(query)
    ranked_items = []
    for item in items:
        match_count, coverage, heading_matches = _lexical_metrics(query, item.get("content", ""))
        exact_subject, prefix_subject = _structured_subject_boost(query, item.get("content", ""))
        ranked_items.append(
            {
                **item,
                "_is_guidance": _is_guidance_chunk(item.get("content", "")),
                "_is_layout": _is_layout_chunk(item.get("content", "")),
                "_exact_subject": exact_subject,
                "_prefix_subject": prefix_subject,
                "_match_count": match_count,
                "_coverage": coverage,
                "_heading_matches": heading_matches,
            }
        )

    ranked_items.sort(
        key=lambda item: (
            int(not item["_is_guidance"]),
            int(not (prefer_profile_chunks and item["_is_layout"])),
            item["_exact_subject"],
            item["_prefix_subject"],
            item["_match_count"],
            item["_coverage"],
            item["_heading_matches"],
            item["score"],
        ),
        reverse=True,
    )

    for item in ranked_items:
        item.pop("_is_guidance", None)
        item.pop("_is_layout", None)
        item.pop("_exact_subject", None)
        item.pop("_prefix_subject", None)
        item.pop("_match_count", None)
        item.pop("_coverage", None)
        item.pop("_heading_matches", None)

    return ranked_items


def retrieve_context(query: str, history: list[dict] | None = None) -> Dict:
    retrieval_query = _build_retrieval_query(query, history=history)
    try:
        collection = get_collection()
        query_vector = embed_texts([retrieval_query])[0]

        result = collection.query(
            query_embeddings=[query_vector],
            n_results=_candidate_count(collection),
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        _logger.exception("rag.retrieve failed query=%s", retrieval_query)
        return {
            "context": "",
            "citations": [],
        }

    documents: List[str] = (result.get("documents") or [[]])[0]
    metadatas: List[dict] = (result.get("metadatas") or [[]])[0]
    distances: List[float] = (result.get("distances") or [[]])[0]

    items = []
    for doc, meta, distance in zip(documents, metadatas, distances):
        if not doc or not str(doc).strip():
            continue
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

    items = _rerank_items(retrieval_query, items)

    if items and not _items_are_relevant(retrieval_query, items):
        return {
            "context": "",
            "citations": [],
        }

    items = items[: settings.rag_top_k]

    context = "\n\n".join(item["content"] for item in items)
    context = context[: settings.rag_max_context_chars]

    return {
        "context": context,
        "citations": items,
    }
