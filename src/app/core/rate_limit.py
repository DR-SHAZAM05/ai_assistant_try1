"""Small, dependency-free rate limiter for the single-process API deployment."""

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int = 0


class SlidingWindowRateLimiter:
    """Concurrency-safe fixed-memory sliding-window limiter."""

    def __init__(
        self,
        *,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_keys = max_keys
        self.clock = clock
        self._buckets: Dict[str, Deque[float]] = {}
        self._lock = asyncio.Lock()

    async def check(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
        if limit <= 0 or window_seconds <= 0:
            return RateLimitDecision(allowed=True, remaining=limit)

        now = self.clock()
        cutoff = now - window_seconds
        async with self._lock:
            self._prune_expired(cutoff)
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= self.max_keys:
                    return RateLimitDecision(allowed=False, remaining=0, retry_after_seconds=window_seconds)
                bucket = deque()
                self._buckets[key] = bucket

            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= limit:
                retry_after = max(1, int(bucket[0] + window_seconds - now) + 1)
                return RateLimitDecision(allowed=False, remaining=0, retry_after_seconds=retry_after)

            bucket.append(now)
            return RateLimitDecision(allowed=True, remaining=limit - len(bucket))

    def _prune_expired(self, cutoff: float) -> None:
        stale_keys = []
        for key, bucket in self._buckets.items():
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if not bucket:
                stale_keys.append(key)
        for key in stale_keys:
            self._buckets.pop(key, None)


telegram_rate_limiter = SlidingWindowRateLimiter()
