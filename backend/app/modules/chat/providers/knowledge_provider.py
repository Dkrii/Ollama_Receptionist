import logging
import time
from typing import Any, Iterable

from modules.chat.constants import CHAT_SYSTEM_FALLBACK
from modules.chat.utils.memory import filter_model_history
from modules.chat.utils.streaming import ndjson_event
from modules.chat.utils.transcript import store_chat_message
from modules.knowledge_base.generate import generate_answer_stream
from modules.knowledge_base.retrieve import retrieve_context


_logger = logging.getLogger(__name__)


def _build_retrieval_result(message: str, history: list[dict]) -> tuple[dict, float]:
    retrieval_started_at = time.perf_counter()
    try:
        retrieval = retrieve_context(message, history=history)
    except Exception:
        _logger.exception("chat.retrieve failed message=%s", message)
        retrieval = {"context": "", "citations": []}

    retrieval_ms = (time.perf_counter() - retrieval_started_at) * 1000
    return retrieval, retrieval_ms


def _build_grounding_note(retrieval: dict[str, Any]) -> str:
    support = retrieval.get("support") if isinstance(retrieval, dict) else {}
    if not isinstance(support, dict):
        support = {}

    grounding = str(support.get("grounding") or "low").strip().lower()
    if grounding == "high":
        return "Konteks sangat relevan. Jawab singkat dan langsung dengan fakta yang tertulis."
    if grounding == "medium":
        return (
            "Konteks cukup relevan, tetapi mungkin hanya menjawab sebagian. "
            "Pastikan setiap detail spesifik yang disebut memang tertulis eksplisit."
        )
    return (
        "Konteks mungkin hanya relevan sebagian. "
        "Gunakan informasi yang ada di konteks jika membantu, sampaikan secara natural. "
        "Untuk detail spesifik (nomor, alamat, jadwal) yang tidak tertulis eksplisit di konteks, akui dengan jujur bahwa informasinya belum tersedia."
    )


def _should_fallback_to_unknown(retrieval: dict[str, Any]) -> bool:
    support = retrieval.get("support") if isinstance(retrieval, dict) else {}
    if not isinstance(support, dict):
        support = {}

    context = str(retrieval.get("context") or "").strip() if isinstance(retrieval, dict) else ""
    citations = retrieval.get("citations") if isinstance(retrieval, dict) else []
    has_citations = isinstance(citations, list) and bool(citations)

    if context or has_citations:
        return False

    grounding = str(support.get("grounding") or "").strip().lower()
    top_coverage = float(support.get("top_coverage") or 0.0)
    top_bigram_coverage = float(support.get("top_bigram_coverage") or 0.0)
    return grounding == "low" and top_coverage <= 0.05 and top_bigram_coverage <= 0.0


def answer_knowledge_stream(
    message: str,
    *,
    conversation_id: str | None,
    history: list[dict] | None,
    flow_state: dict,
) -> Iterable[str]:
    started_at = time.perf_counter()
    prior_history = history or []
    model_history = filter_model_history(prior_history)

    store_chat_message(conversation_id, "user", message)
    retrieval, retrieval_ms = _build_retrieval_result(message, model_history)

    def _events() -> Iterable[str]:
        collected_tokens: list[str] = []
        try:
            meta_payload: dict[str, Any] = {
                "route": "knowledge",
                "flow_state": flow_state,
            }
            if conversation_id:
                meta_payload["conversation_id"] = conversation_id
            yield ndjson_event("meta", **meta_payload)

            if _should_fallback_to_unknown(retrieval):
                fallback_answer = "Maaf, saya belum punya informasi pastinya untuk itu. Apakah ada hal lain yang ingin Anda tanyakan?"
                store_chat_message(conversation_id, "assistant", fallback_answer)
                yield ndjson_event("token", fallback_answer)
                yield ndjson_event("citations", retrieval.get("citations") or [])
                yield ndjson_event("done")
                return

            first_token_logged = False
            for token in generate_answer_stream(
                message,
                retrieval["context"],
                history=model_history,
                grounding_note=_build_grounding_note(retrieval),
            ):
                if not first_token_logged and token:
                    first_token_ms = (time.perf_counter() - started_at) * 1000
                    _logger.info(
                        "chat.stream route=knowledge conversation_id=%s retrieval_ms=%.1f first_token_ms=%.1f",
                        conversation_id,
                        retrieval_ms,
                        first_token_ms,
                    )
                    first_token_logged = True
                if token:
                    collected_tokens.append(token)
                yield ndjson_event("token", token)

            final_answer = "".join(collected_tokens).strip()
            if final_answer:
                store_chat_message(conversation_id, "assistant", final_answer)
            yield ndjson_event("citations", retrieval.get("citations") or [])
            yield ndjson_event("done")
        except Exception:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            _logger.exception(
                "chat.stream route=knowledge failed conversation_id=%s retrieval_ms=%.1f total_ms=%.1f",
                conversation_id,
                retrieval_ms,
                elapsed_ms,
            )
            yield ndjson_event("error", CHAT_SYSTEM_FALLBACK)

    return _events()
