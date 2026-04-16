import json
import logging
import time
from typing import Any

from api.chat.utils import store_chat_message
from rag.generate import generate_answer_stream
from rag.retrieve import retrieve_context

_logger = logging.getLogger(__name__)
CHAT_SYSTEM_FALLBACK = "Maaf, sistem sedang mengalami gangguan. Silakan coba lagi sebentar."


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
        "Konteks hanya berkaitan sebagian atau lemah. "
        "Jangan memberikan lokasi, nomor, nama, jadwal, atau detail spesifik kecuali benar-benar tertulis jelas."
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


def ask_stream(
    message: str,
    conversation_id: str | None,
    history: list[dict] | None,
    flow_state: dict[str, Any] | None = None,
):
    started_at = time.perf_counter()
    prior_history = history or []

    store_chat_message(conversation_id, "user", message)
    retrieval, retrieval_ms = _build_retrieval_result(message, prior_history)

    def _events():
        collected_tokens: list[str] = []
        try:
            meta_payload = {
                "type": "meta",
                "route": "rag",
                "flow_state": flow_state or {"stage": "idle"},
            }
            if conversation_id:
                meta_payload["conversation_id"] = conversation_id
            yield json.dumps(meta_payload, ensure_ascii=False) + "\n"

            if _should_fallback_to_unknown(retrieval):
                fallback_answer = "Maaf, saya belum menemukan informasi pastinya di knowledge yang tersedia."
                store_chat_message(conversation_id, "assistant", fallback_answer)
                yield json.dumps({"type": "token", "value": fallback_answer}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "citations", "value": retrieval["citations"]}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
                return

            first_token_logged = False
            for token in generate_answer_stream(
                message,
                retrieval["context"],
                history=prior_history,
                grounding_note=_build_grounding_note(retrieval),
            ):
                if not first_token_logged and token:
                    first_token_ms = (time.perf_counter() - started_at) * 1000
                    _logger.info(
                        "chat.stream route=rag conversation_id=%s retrieval_ms=%.1f first_token_ms=%.1f",
                        conversation_id,
                        retrieval_ms,
                        first_token_ms,
                    )
                    first_token_logged = True
                if token:
                    collected_tokens.append(token)
                yield json.dumps({"type": "token", "value": token}, ensure_ascii=False) + "\n"

            final_answer = "".join(collected_tokens).strip()
            if final_answer:
                store_chat_message(conversation_id, "assistant", final_answer)
            yield json.dumps({"type": "citations", "value": retrieval["citations"]}, ensure_ascii=False) + "\n"
            yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
        except Exception:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            _logger.exception(
                "chat.stream route=rag failed conversation_id=%s retrieval_ms=%.1f total_ms=%.1f",
                conversation_id,
                retrieval_ms,
                elapsed_ms,
            )
            yield json.dumps(
                {"type": "error", "value": CHAT_SYSTEM_FALLBACK},
                ensure_ascii=False,
            ) + "\n"

    return _events()
