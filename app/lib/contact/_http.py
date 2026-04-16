import requests
from typing import Any

from config import settings


_http_session = requests.Session()


def request_timeout(setting_name: str, fallback: int = 15) -> int:
    return max(5, int(getattr(settings, setting_name, fallback) or fallback))


def response_payload(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
        return payload if isinstance(payload, dict) else {"payload": payload}
    except Exception:
        text = (response.text or "").strip()
        return {"raw_text": text[:1000]}


def post_json(
    *,
    url: str,
    payload: dict[str, Any],
    bearer_token: str = "",
    timeout_seconds: int = 15,
) -> tuple[requests.Response, dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    response = _http_session.post(
        url,
        json=payload,
        headers=headers,
        timeout=max(5, int(timeout_seconds or 15)),
    )
    response.raise_for_status()
    return response, response_payload(response)


def post_form(
    *,
    url: str,
    payload: dict[str, Any],
    basic_auth_username: str = "",
    basic_auth_password: str = "",
    timeout_seconds: int = 15,
) -> tuple[requests.Response, dict[str, Any]]:
    response = _http_session.post(
        url,
        data=payload,
        auth=(basic_auth_username, basic_auth_password) if basic_auth_username or basic_auth_password else None,
        timeout=max(5, int(timeout_seconds or 15)),
    )
    response.raise_for_status()
    return response, response_payload(response)
