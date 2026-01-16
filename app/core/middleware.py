"""Shared FastAPI middleware."""

from __future__ import annotations

from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from app.core.config import get_settings


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    """
    Reject requests with bodies larger than MAX_REQUEST_BODY_BYTES.

    COST-001: protects against base64 DoS and runaway payload sizes.
    """

    async def dispatch(self, request: Request, call_next: Callable[[Request], Response]) -> Response:
        settings = get_settings()
        limit = int(getattr(settings, "MAX_REQUEST_BODY_BYTES", 2_000_000))

        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > limit:
                    return JSONResponse({"detail": "Payload too large."}, status_code=413)
            except ValueError:
                pass

        # For chunked / missing content-length, read body and enforce size.
        # Starlette caches request.body() so downstream handlers still can read it.
        try:
            body = await request.body()
        except Exception:
            return JSONResponse({"detail": "Invalid request body."}, status_code=400)

        if body and len(body) > limit:
            return JSONResponse({"detail": "Payload too large."}, status_code=413)

        return await call_next(request)

