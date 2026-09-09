"""
Day 13 — Basic rate limiting for AI-path endpoints. See docs/acceptance-criteria.md, section 4.

TRUST PRINCIPLE: Reliability

Business Purpose:
    /chat and /chat/stream are the only endpoints that cost real compute
    (a CPU-only 3B model inference, per BUG-004's own finding) - they're
    the ones worth protecting from being hammered, not the free filter
    path which costs single-digit milliseconds regardless of volume.

Design Decision:
    A plain in-memory sliding-window counter, per client IP, no external
    dependency (no Redis, no slowapi) - consistent with this project's
    standing mocked-but-honest pattern for anything beyond its actual
    scope (see conversation.py's session store, agent.py's mock cart).
    Explicitly NOT a production-grade distributed rate limiter; a
    single-process, in-memory counter is what "basic rate limiting" for
    a practice project honestly means, and is stated as such rather than
    dressed up as more than it is.

Failure Strategy:
    Resets on every backend restart, same limitation conversation.py's
    history already carries and already documents - not a new risk
    introduced here, a repeated one, worth naming again in this new
    context rather than assuming it's obvious. A client behind a shared
    IP (NAT, corporate proxy) shares one limit - a known, accepted
    trade-off of IP-based limiting at this scope, not a hidden one.

Future Validation:
    If this is ever deployed somewhere real traffic could hit shared-IP
    false limiting, or multiple backend processes/replicas (this
    in-memory counter is NOT shared across processes), that's the signal
    to move to a real distributed limiter (Redis-backed), not a reason to
    complicate this one preemptively.
"""
import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request

WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = 10

_lock = Lock()
_hits: dict = defaultdict(list)


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit_ai_path(request: Request) -> None:
    """FastAPI dependency - raises HTTPException(429) if this client has
    exceeded MAX_REQUESTS_PER_WINDOW requests in the last WINDOW_SECONDS."""
    key = _client_key(request)
    now = time.monotonic()

    with _lock:
        window = _hits[key]
        while window and window[0] <= now - WINDOW_SECONDS:
            window.pop(0)

        if len(window) >= MAX_REQUESTS_PER_WINDOW:
            retry_after = WINDOW_SECONDS - (now - window[0])
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Too many requests - please wait {retry_after:.0f}s "
                    f"and try again."
                ),
                headers={"Retry-After": str(max(1, round(retry_after)))},
            )

        window.append(now)
