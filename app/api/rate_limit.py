"""Per-client sliding-window rate limit (TZ 9.2, API gateway layer).

In-process by design for the single-node pilot: state lives in a deque per
client key, no Redis dependency. Multi-node deployments replace this with a
shared counter - the middleware contract stays the same. Health endpoints
stay unlimited; every other route counts against the client window.
"""

import hashlib
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_WINDOW_SECONDS = 60
_MAX_TRACKED_CLIENTS = 10_000


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

    @staticmethod
    def _client_key(request: Request) -> str:
        # Behind the frontend reverse proxy every request shares the proxy IP,
        # so the bearer token is the meaningful per-caller identity. The hash
        # keeps raw credentials out of process memory.
        authorization = request.headers.get("authorization", "")
        if authorization:
            digest = hashlib.sha256(authorization.encode()).hexdigest()
            return f"token:{digest}"
        return request.client.host if request.client else "anonymous"

    def _evict_stale(self, now: float) -> None:
        for key in [
            key
            for key, window in self._windows.items()
            if not window or now - window[-1] > _WINDOW_SECONDS
        ]:
            self._windows.pop(key, None)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not self.enabled or request.url.path in {"/health", "/ready", "/metrics"}:
            return await call_next(request)
        client = self._client_key(request)
        now = time.monotonic()
        window = self._windows[client]
        while window and now - window[0] > _WINDOW_SECONDS:
            window.popleft()
        if len(window) >= self.limit:
            retry_after = int(_WINDOW_SECONDS - (now - window[0])) + 1
            return JSONResponse(
                status_code=429,
                content={"code": "RATE_LIMITED", "retry_after_seconds": retry_after},
                headers={"Retry-After": str(retry_after)},
            )
        window.append(now)
        # Bounded memory: drop idle callers when the map grows past the cap.
        if len(self._windows) > _MAX_TRACKED_CLIENTS:
            self._evict_stale(now)
        return await call_next(request)
