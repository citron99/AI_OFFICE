"""Per-client sliding-window rate limit (TZ 9.2, API gateway layer).

In-process by design for the single-node pilot: state lives in a deque per
client key, no Redis dependency. Multi-node deployments replace this with a
shared counter - the middleware contract stays the same. Health endpoints
stay unlimited; every other route counts against the client window.
"""

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: Callable[..., Any],  # starlette ASGI app typing is nominal
        *,
        limit_per_minute: int,
        enabled: bool = True,
    ) -> None:
        super().__init__(app)
        self.limit = limit_per_minute
        self.enabled = enabled
        self._windows: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not self.enabled or request.url.path in {"/health", "/ready", "/metrics"}:
            return await call_next(request)
        client = request.client.host if request.client else "anonymous"
        now = time.monotonic()
        window = self._windows[client]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self.limit:
            retry_after = int(60 - (now - window[0])) + 1
            return JSONResponse(
                status_code=429,
                content={"code": "RATE_LIMITED", "retry_after_seconds": retry_after},
                headers={"Retry-After": str(retry_after)},
            )
        window.append(now)
        # Bounded memory: drop idle clients when the map grows past 10k.
        if len(self._windows) > 10_000:
            for key in [k for k, w in self._windows.items() if not w][:5_000]:
                self._windows.pop(key, None)
        return await call_next(request)
