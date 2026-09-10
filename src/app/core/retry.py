import asyncio
from typing import Awaitable, Callable, TypeVar

from src.app.core.config import settings
from src.app.core.logging import logger


T = TypeVar("T")


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = None,
    timeout_seconds: float = None,
    base_delay_seconds: float = 0.25,
    operation_name: str = "external_operation",
) -> T:
    """
    Run an async external operation with timeout and small exponential backoff.
    """
    max_attempts = max(1, attempts or settings.EXTERNAL_RETRY_ATTEMPTS)
    timeout = timeout_seconds or settings.EXTERNAL_REQUEST_TIMEOUT_SECONDS
    last_error = None

    for attempt in range(1, max_attempts + 1):
        try:
            return await asyncio.wait_for(operation(), timeout=timeout)
        except Exception as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
            delay = base_delay_seconds * (2 ** (attempt - 1))
            logger.warning(
                "%s failed on attempt %s/%s (%s). Retrying in %.2fs.",
                operation_name,
                attempt,
                max_attempts,
                type(exc).__name__,
                delay,
            )
            await asyncio.sleep(delay)

    raise last_error
