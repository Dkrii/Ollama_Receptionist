import json
from typing import Any, Iterable


def ndjson_event(event_type: str, value: Any | None = None, **extra: Any) -> str:
    payload: dict[str, Any] = {"type": event_type}
    if value is not None:
        payload["value"] = value
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False) + "\n"


def static_chat_events(
    *,
    answer: str,
    conversation_id: str | None,
    flow_state: dict,
    route: str,
    citations: list | None = None,
) -> Iterable[str]:
    meta_payload: dict[str, Any] = {
        "route": route,
        "flow_state": flow_state,
    }
    if conversation_id:
        meta_payload["conversation_id"] = conversation_id

    yield ndjson_event("meta", **meta_payload)
    if answer:
        yield ndjson_event("token", answer)
    yield ndjson_event("citations", citations or [])
    yield ndjson_event("done")
