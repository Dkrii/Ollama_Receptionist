import time
import logging
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("api")


def _request_id_from_headers(request: Request) -> str:
    candidate = str(request.headers.get("x-request-id") or "").strip()
    return candidate or uuid.uuid4().hex[:12]


class RequestLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()
        request_id = _request_id_from_headers(request)
        request.state.request_id = request_id
        client_ip = request.client.host if request.client else "127.0.0.1"

        try:
            response = await call_next(request)
        except Exception:
            process_time = (time.perf_counter() - start_time) * 1000
            logger.exception(
                "http.request id=%s ip=%s method=%s path=%s status=500 duration_ms=%.2f",
                request_id,
                client_ip,
                request.method,
                request.url.path,
                process_time,
            )
            raise

        process_time = (time.perf_counter() - start_time) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "http.request id=%s ip=%s method=%s path=%s status=%s duration_ms=%.2f",
            request_id,
            client_ip,
            request.method,
            request.url.path,
            response.status_code,
            process_time,
        )

        return response
