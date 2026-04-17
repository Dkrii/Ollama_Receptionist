import requests
from typing import Any


_http_session = requests.Session()


def request_timeout(raw_value: int | str | None, fallback: int = 15) -> int:
    try:
        timeout = int(raw_value or fallback)
    except Exception:
        timeout = fallback
    return max(5, timeout)


def response_payload(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
        return payload if isinstance(payload, dict) else {"payload": payload}
    except Exception:
        text = (response.text or "").strip()
        return {"raw_text": text[:1000]}


def post_form(
    *,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout_seconds: int = 15,
) -> tuple[requests.Response, dict[str, Any]]:
    merged_headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if headers:
        merged_headers.update(headers)

    response = _http_session.post(
        url,
        data=payload,
        headers=merged_headers,
        timeout=max(5, int(timeout_seconds or 15)),
    )
    return response, response_payload(response)
