import json
import logging
import time

from api.chat.intent import is_social_message
from api.chat.repository import ChatRepository
from config import settings
from rag.generate import generate_answer, generate_answer_stream
from rag.retrieve import retrieve_context

_logger = logging.getLogger(__name__)
CHAT_SYSTEM_FALLBACK = "Maaf, sistem sedang mengalami gangguan. Silakan coba lagi sebentar."
CHAT_KNOWLEDGE_FALLBACK = "Maaf, informasi belum tersedia saat ini. Silakan hubungi petugas."


def _trim_history(history: list[dict] | None) -> list[dict]:
    if not history:
        return []

    trimmed_history: list[dict] = []
    for item in history[-settings.chat_recent_turns:]:
        role = str(item.get("role", "")).strip()
        content = str(item.get("content", "")).strip()
        if not role or not content:
            continue
        trimmed_history.append({"role": role, "content": content})
    return trimmed_history


def _resolve_chat_memory(conversation_id: str | None, history: list[dict] | None = None) -> tuple[str | None, list[dict], bool]:
    fallback_history = _trim_history(history)
    try:
        resolved_conversation_id = ChatRepository.resolve_conversation(conversation_id)
        prior_history = ChatRepository.get_recent_turns(resolved_conversation_id)
        if not prior_history and not conversation_id:
            prior_history = fallback_history
        return resolved_conversation_id, prior_history, True
    except Exception:
        _logger.exception("chat.memory unavailable conversation_id=%s", conversation_id)
        return None, fallback_history, False


def _store_chat_message(conversation_id: str | None, role: str, content: str) -> None:
    if not conversation_id:
        return
    try:
        ChatRepository.add_message(conversation_id, role, content)
    except Exception:
        _logger.exception("chat.memory write failed conversation_id=%s role=%s", conversation_id, role)


def _build_answer_payload(answer: str, citations: list[dict], conversation_id: str | None) -> dict:
    payload = {
        "answer": answer,
        "citations": citations,
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    return payload


def _build_retrieval_result(message: str, history: list[dict]) -> tuple[dict, float]:
    if is_social_message(message):
        return {"context": "", "citations": []}, 0.0

    retrieval_started_at = time.perf_counter()
    try:
        retrieval = retrieve_context(message, history=history)
    except Exception:
        _logger.exception("chat.retrieve failed message=%s", message)
        retrieval = {"context": "", "citations": []}
    retrieval_ms = (time.perf_counter() - retrieval_started_at) * 1000
    return retrieval, retrieval_ms


# def _fallback_answer_from_retrieval(message: str, retrieval: dict) -> str | None:
#     if is_social_message(message):
#         return None
#     if retrieval.get("context", "").strip():
#         return None
#     return CHAT_KNOWLEDGE_FALLBACK


class ChatAppService:
    @staticmethod
    def ask(message: str, conversation_id: str | None = None, history: list[dict] | None = None) -> dict:
        started_at = time.perf_counter()
        resolved_conversation_id, prior_history, _ = _resolve_chat_memory(conversation_id, history=history)
        try:
            _store_chat_message(resolved_conversation_id, "user", message)

            retrieval, retrieval_ms = _build_retrieval_result(message, prior_history)

            # fallback_answer = _fallback_answer_from_retrieval(message, retrieval)
            # if fallback_answer:
            #     _store_chat_message(resolved_conversation_id, "assistant", fallback_answer)
            #     return _build_answer_payload(fallback_answer, retrieval["citations"], resolved_conversation_id)

            answer_started_at = time.perf_counter()
            answer = generate_answer(message, retrieval["context"], history=prior_history)
            answer_ms = (time.perf_counter() - answer_started_at) * 1000
            _store_chat_message(resolved_conversation_id, "assistant", answer)

            elapsed_ms = (time.perf_counter() - started_at) * 1000
            _logger.info(
                "chat.ask route=rag conversation_id=%s retrieval_ms=%.1f answer_ms=%.1f total_ms=%.1f",
                resolved_conversation_id,
                retrieval_ms,
                answer_ms,
                elapsed_ms,
            )
            return _build_answer_payload(answer, retrieval["citations"], resolved_conversation_id)
        except Exception:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            _logger.exception(
                "chat.ask route=rag failed conversation_id=%s total_ms=%.1f",
                resolved_conversation_id,
                elapsed_ms,
            )
            return _build_answer_payload(CHAT_SYSTEM_FALLBACK, [], resolved_conversation_id)

    @staticmethod
    def ask_stream(message: str, conversation_id: str | None = None, history: list[dict] | None = None):
        started_at = time.perf_counter()
        resolved_conversation_id, prior_history, _ = _resolve_chat_memory(conversation_id, history=history)

        _store_chat_message(resolved_conversation_id, "user", message)

        retrieval, retrieval_ms = _build_retrieval_result(message, prior_history)

        def _events():
            collected_tokens: list[str] = []
            try:
                meta_payload = {"type": "meta"}
                if resolved_conversation_id:
                    meta_payload["conversation_id"] = resolved_conversation_id
                yield json.dumps(meta_payload, ensure_ascii=False) + "\n"

                # fallback_answer = _fallback_answer_from_retrieval(message, retrieval)
                # if fallback_answer:
                #     _store_chat_message(resolved_conversation_id, "assistant", fallback_answer)
                #     yield json.dumps({"type": "token", "value": fallback_answer}, ensure_ascii=False) + "\n"
                #     yield json.dumps({"type": "citations", "value": retrieval["citations"]}, ensure_ascii=False) + "\n"
                #     yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
                #     return

                first_token_logged = False
                for token in generate_answer_stream(message, retrieval["context"], history=prior_history):
                    if not first_token_logged and token:
                        first_token_ms = (time.perf_counter() - started_at) * 1000
                        _logger.info(
                            "chat.stream route=rag conversation_id=%s retrieval_ms=%.1f first_token_ms=%.1f",
                            resolved_conversation_id,
                            retrieval_ms,
                            first_token_ms,
                        )
                        first_token_logged = True
                    if token:
                        collected_tokens.append(token)
                    yield json.dumps({"type": "token", "value": token}, ensure_ascii=False) + "\n"
                final_answer = "".join(collected_tokens).strip()
                if final_answer:
                    _store_chat_message(resolved_conversation_id, "assistant", final_answer)
                yield json.dumps({"type": "citations", "value": retrieval["citations"]}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
            except Exception:
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                _logger.exception(
                    "chat.stream route=rag failed conversation_id=%s retrieval_ms=%.1f total_ms=%.1f",
                    resolved_conversation_id,
                    retrieval_ms,
                    elapsed_ms,
                )
                yield json.dumps(
                    {"type": "error", "value": CHAT_SYSTEM_FALLBACK},
                    ensure_ascii=False,
                ) + "\n"

        return _events()
