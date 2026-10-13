import os
import asyncio
import time
from collections import defaultdict
from typing import Dict, List, Optional
from fastapi import HTTPException, Request, status

from app.core.config import settings


class InMemoryRateLimiter:
    """
    Thread-safe, sliding-window rate limiter for sensitive endpoints.
    Tracks timestamps of requests per client key (IP address or user identifier).
    """

    def __init__(self):
        # Maps key -> list of float epoch timestamps
        self._records: Dict[str, List[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    def _get_client_key(self, request: Request, custom_key: Optional[str] = None) -> str:
        if custom_key:
            return custom_key

        # Check proxy headers (Cloudflare / reverse proxy / load balancer)
        forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown_client"

        path = request.url.path
        return f"{client_ip}:{path}"

    async def check_rate_limit(
        self,
        request: Request,
        max_requests: int,
        window_seconds: int = 60,
        custom_key: Optional[str] = None,
    ) -> None:
        """
        Enforce rate limit. If limit is exceeded, raises HTTP 429 Too Many Requests.
        """
        # Allow disabling rate limiter in automated test runs unless explicitly tested
        is_test_env = (
            bool(os.getenv("PYTEST_CURRENT_TEST"))
            or getattr(settings, "APP_ENV", "") == "testing"
        )
        if is_test_env and not getattr(request.state, "test_enforce_rate_limit", False):
            return

        key = self._get_client_key(request, custom_key)
        now = time.time()
        window_start = now - window_seconds

        async with self._lock:
            # Purge entries older than the sliding window
            timestamps = [ts for ts in self._records[key] if ts > window_start]

            if len(timestamps) >= max_requests:
                earliest_ts = min(timestamps)
                retry_after = int(max(1, window_seconds - (now - earliest_ts)))

                self._records[key] = timestamps
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Please slow down and try again later.",
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(max_requests),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(int(earliest_ts + window_seconds)),
                    },
                )

            timestamps.append(now)
            self._records[key] = timestamps

    def reset(self) -> None:
        """Clear all rate limit records (useful between test runs)."""
        self._records.clear()


limiter = InMemoryRateLimiter()


def rate_limit(max_requests: int, window_seconds: int = 60):
    """
    FastAPI dependency generator for endpoint-level rate limiting.
    Example: Depends(rate_limit(max_requests=10, window_seconds=60))
    """
    async def dependency(request: Request):
        await limiter.check_rate_limit(request, max_requests=max_requests, window_seconds=window_seconds)
    return dependency
