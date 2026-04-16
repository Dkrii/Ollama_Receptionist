import time
import logging
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("api")

class RequestLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()
        
        # Mengeksekusi request ke route selanjutnya
        response = await call_next(request)
        
        process_time = (time.perf_counter() - start_time) * 1000
        client_ip = request.client.host if request.client else "127.0.0.1"
        
        # Format log yang mudah dibaca
        logger.info(
            f"HTTPRequest | {client_ip} | {request.method} {request.url.path} "
            f"| Status: {response.status_code} | Time: {process_time:.2f}ms"
        )
        
        return response
