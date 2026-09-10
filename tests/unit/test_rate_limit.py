import pytest

from src.app.core.rate_limit import SlidingWindowRateLimiter


class Clock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


@pytest.mark.asyncio
async def test_sliding_window_limiter_enforces_and_expires_limits():
    clock = Clock()
    limiter = SlidingWindowRateLimiter(clock=clock)

    assert (await limiter.check("student-1", limit=2, window_seconds=60)).allowed
    assert (await limiter.check("student-1", limit=2, window_seconds=60)).allowed
    rejected = await limiter.check("student-1", limit=2, window_seconds=60)
    assert not rejected.allowed
    assert rejected.retry_after_seconds > 0

    clock.value += 61
    assert (await limiter.check("student-1", limit=2, window_seconds=60)).allowed


@pytest.mark.asyncio
async def test_sliding_window_limiter_keeps_users_separate():
    limiter = SlidingWindowRateLimiter()

    assert (await limiter.check("student-1", limit=1, window_seconds=60)).allowed
    assert not (await limiter.check("student-1", limit=1, window_seconds=60)).allowed
    assert (await limiter.check("student-2", limit=1, window_seconds=60)).allowed
