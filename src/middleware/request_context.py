"""
Reusable request-context middleware: correlation IDs + server-timing.
=====================================================================

Every request gets a stable X-Request-ID (honored from the client if provided,
else generated). The ID is:
  - attached to request.state.request_id for handlers to read,
  - stashed in a contextvar so ANY code deep in the call stack (services, RAG
    pipeline, tracing) can grab it without threading it through every function,
  - echoed back in the response header so a user's bug report maps to a log line.

This is the backbone that ties logs + OpenTelemetry spans together. It's the
first middleware you want in any service, which is why it lives on its own.
"""
from __future__ import annotations

import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        rid = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]
        request.state.request_id = rid
        token = request_id_ctx.set(rid)

        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)

        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers[REQUEST_ID_HEADER] = rid
        response.headers["Server-Timing"] = f"app;dur={elapsed_ms:.1f}"
        return response


def current_request_id() -> str:
    return request_id_ctx.get()
