import json
import logging
import re
import time

from config import settings
from rag.generate import (
    classify_social_with_reply,
    ensure_indonesian_text,
    generate_answer,
    generate_answer_stream,
    generate_social_answer,
)
from rag.retrieve import retrieve_context


_social_cache: dict[str, tuple[float, str]] = {}
_logger = logging.getLogger(__name__)

_SOCIAL_DIRECT_KEYS = {
    "__social_greeting__",
    "__social_thanks__",
    "selamat pagi",
    "selamat siang",
    "selamat sore",
    "selamat malam",
    "apa kabar",
    "permisi",
}


def _normalize_social_key(text: str) -> str:
    lowered = text.lower().strip()
    lowered = re.sub(r"[^a-zA-Z0-9\s]", " ", lowered)
    lowered = re.sub(r"([a-z])\1{2,}", r"\1\1", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()

    greeting_aliases = {
        "hai",
        "halo",
        "hallo",
        "helo",
        "hello",
        "hi",
        "pagi",
        "siang",
        "sore",
        "malam",
        "assalamualaikum",
    }
    thanks_aliases = {
        "terima kasih",
        "terimakasih",
        "makasih",
        "thanks",
        "thank you",
    }

    if lowered in greeting_aliases:
        return "__social_greeting__"

    if lowered in thanks_aliases:
        return "__social_thanks__"

    return lowered


def _get_cached_social_answer(message: str) -> str | None:
    key = _normalize_social_key(message)
    if not key:
        return None

    cached = _social_cache.get(key)
    if not cached:
        return None

    expires_at, answer = cached
    if time.time() >= expires_at:
        _social_cache.pop(key, None)
        return None
    normalized = ensure_indonesian_text(answer)
    if normalized != answer:
        _cache_social_answer(message, normalized)
    return normalized


def _cache_social_answer(message: str, answer: str) -> None:
    key = _normalize_social_key(message)
    if not key or not answer:
        return

    ttl = max(0, settings.social_cache_ttl_seconds)
    if ttl == 0:
        return

    _social_cache[key] = (time.time() + ttl, answer)


def _should_route_social(message: str) -> bool:
    normalized = _normalize_social_key(message)
    if not normalized:
        return False

    return normalized in _SOCIAL_DIRECT_KEYS


def _iter_cached_answer_tokens(answer: str):
    words = [word for word in answer.split() if word]
    if not words:
        yield answer
        return

    for idx, word in enumerate(words):
        if idx == 0:
            yield word
        else:
            yield f" {word}"


def _is_usable_social_answer(answer: str) -> bool:
    text = (answer or "").strip()
    if not text:
        return False

    if "|" in text:
        return False

    words = text.split()
    if len(words) < 3:
        return False

    lowered = text.lower()
    if lowered in {"sapaan", "greeting", "social"}:
        return False

    return True


def _resolve_social_answer(message: str, social_answer: str) -> str:
    candidate = (social_answer or "").strip()
    if not _is_usable_social_answer(candidate):
        candidate = generate_social_answer(message)

    candidate = ensure_indonesian_text(candidate)
    if not _is_usable_social_answer(candidate):
        candidate = generate_social_answer(message)
        candidate = ensure_indonesian_text(candidate)

    _cache_social_answer(message, candidate)
    return candidate


class ChatService:
    @staticmethod
    def ask(message: str) -> dict:
        started_at = time.perf_counter()
        should_route_social = _should_route_social(message)
        if should_route_social:
            cached_answer = _get_cached_social_answer(message)
            if cached_answer:
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                _logger.info("chat.ask route=social_cache total_ms=%.1f", elapsed_ms)
                return {
                    "answer": cached_answer,
                    "citations": [],
                }

            intent, social_answer = classify_social_with_reply(message)
            if intent == "social":
                answer = _resolve_social_answer(message, social_answer)
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                _logger.info("chat.ask route=social_llm total_ms=%.1f", elapsed_ms)
                return {
                    "answer": answer,
                    "citations": [],
                }

        retrieval_started_at = time.perf_counter()
        retrieval = retrieve_context(message)
        retrieval_ms = (time.perf_counter() - retrieval_started_at) * 1000

        answer_started_at = time.perf_counter()
        answer = generate_answer(message, retrieval["context"])
        answer_ms = (time.perf_counter() - answer_started_at) * 1000
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        _logger.info(
            "chat.ask route=rag retrieval_ms=%.1f answer_ms=%.1f total_ms=%.1f",
            retrieval_ms,
            answer_ms,
            elapsed_ms,
        )
        return {
            "answer": answer,
            "citations": retrieval["citations"],
        }

    @staticmethod
    def ask_stream(message: str):
        started_at = time.perf_counter()
        should_route_social = _should_route_social(message)
        if should_route_social:
            cached_answer = _get_cached_social_answer(message)
            if cached_answer:
                def _cached_social_events():
                    elapsed_ms = (time.perf_counter() - started_at) * 1000
                    _logger.info("chat.stream route=social_cache first_token_ms=%.1f", elapsed_ms)
                    for token in _iter_cached_answer_tokens(cached_answer):
                        yield json.dumps({"type": "token", "value": token}, ensure_ascii=False) + "\n"
                    yield json.dumps({"type": "citations", "value": []}, ensure_ascii=False) + "\n"
                    yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"

                return _cached_social_events()

            intent, social_answer = classify_social_with_reply(message)
            if intent == "social":
                def _social_events():
                    answer = _resolve_social_answer(message, social_answer)
                    elapsed_ms = (time.perf_counter() - started_at) * 1000
                    _logger.info("chat.stream route=social_llm first_token_ms=%.1f", elapsed_ms)
                    for token in _iter_cached_answer_tokens(answer):
                        yield json.dumps({"type": "token", "value": token}, ensure_ascii=False) + "\n"
                    yield json.dumps({"type": "citations", "value": []}, ensure_ascii=False) + "\n"
                    yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"

                return _social_events()

        retrieval_started_at = time.perf_counter()
        retrieval = retrieve_context(message)
        retrieval_ms = (time.perf_counter() - retrieval_started_at) * 1000

        def _events():
            try:
                first_token_logged = False
                for token in generate_answer_stream(message, retrieval["context"]):
                    if not first_token_logged and token:
                        first_token_ms = (time.perf_counter() - started_at) * 1000
                        _logger.info(
                            "chat.stream route=rag retrieval_ms=%.1f first_token_ms=%.1f",
                            retrieval_ms,
                            first_token_ms,
                        )
                        first_token_logged = True
                    yield json.dumps({"type": "token", "value": token}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "citations", "value": retrieval["citations"]}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
            except Exception:
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                _logger.exception(
                    "chat.stream route=rag failed retrieval_ms=%.1f total_ms=%.1f",
                    retrieval_ms,
                    elapsed_ms,
                )
                yield json.dumps(
                    {"type": "error", "value": "Terjadi kesalahan saat memproses pertanyaan."},
                    ensure_ascii=False,
                ) + "\n"

        return _events()
