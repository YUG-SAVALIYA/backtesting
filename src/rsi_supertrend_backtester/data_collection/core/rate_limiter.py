"""
Token bucket rate limiter for controlling request rate to DhanHQ API.

Implements a thread-safe async token bucket with configurable rate
and burst capacity.
"""
import asyncio
import time
from rsi_supertrend_backtester.data_collection.utils.logger import get_logger

logger = get_logger(__name__)


class AsyncTokenBucket:
    """
    Async token bucket rate limiter.

    Allows up to `rate` tokens per second with a burst capacity of `capacity`.
    Callers await `acquire()` which blocks until a token is available.
    """

    def __init__(self, rate: float, capacity: float):
        """
        Args:
            rate: Tokens added per second (e.g., 2.0 for 2 RPS)
            capacity: Maximum tokens (burst size)
        """
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity  # Start full
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        """
        Acquire tokens, blocking until available.

        Args:
            tokens: Number of tokens to consume (default 1).
        """
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                # Calculate wait time for enough tokens to accumulate
                wait_time = (tokens - self._tokens) / self._rate

            logger.debug(f"Rate limiter: waiting {wait_time:.2f}s for token")
            await asyncio.sleep(wait_time)

    def _refill(self) -> None:
        """Add tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        added = elapsed * self._rate
        self._tokens = min(self._capacity, self._tokens + added)
        self._last_refill = now


# Global singleton rate limiter (shared across all DhanHQ requests)
_global_limiter: AsyncTokenBucket | None = None


def get_rate_limiter() -> AsyncTokenBucket:
    """Get or create the global rate limiter instance."""
    global _global_limiter
    if _global_limiter is None:
        from rsi_supertrend_backtester.data_collection.config import settings
        _global_limiter = AsyncTokenBucket(
            rate=settings.rate_limit_rps,
            capacity=settings.rate_limit_burst,
        )
        logger.info(
            f"Rate limiter initialized: {settings.rate_limit_rps} RPS, "
            f"burst={settings.rate_limit_burst}"
        )
    return _global_limiter
