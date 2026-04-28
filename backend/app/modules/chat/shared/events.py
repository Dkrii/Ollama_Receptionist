import json
from typing import Any


def ndjson_event(event_type: str, value: Any | None = None, **extra: Any) -> str:
    payload: dict[str, Any] = {"type": event_type}
    if value is not None:
        payload["value"] = value
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False) + "\n"
