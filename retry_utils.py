"""
retry_utils.py — Exponential backoff retry for external API calls.
"""

import time
import random
from functools import wraps
from typing import Callable, Tuple, Type


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_exceptions: Tuple[Type[BaseException], ...] = (Exception,),
    retryable_check: Callable[[Exception], bool] | None = None,
):
    """
    Decorator that retries a function with exponential backoff + jitter.

    Args:
        max_retries: Total attempts (1 = no retries, 3 = up to 2 retries).
        base_delay: Initial delay in seconds before first retry.
        max_delay: Cap on the backoff delay.
        retryable_exceptions: Tuple of exception types eligible for retry.
        retryable_check: Optional callable — receives the exception, returns
            True if it should be retried. Overrides retryable_exceptions when
            provided alongside them.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    if retryable_check and not retryable_check(e):
                        raise
                    last_exc = e
                    if attempt == max_retries:
                        raise
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    delay *= 0.5 + random.random()  # jitter
                    print(f"  ↻ Retry {attempt}/{max_retries - 1} for {func.__name__} "
                          f"after {delay:.1f}s — {type(e).__name__}: {str(e)[:120]}")
                    time.sleep(delay)
            raise last_exc  # unreachable, but satisfies type checker
        return wrapper
    return decorator


def is_transient_api_error(e: Exception) -> bool:
    """Return True for errors that are likely transient (rate limits, server errors)."""
    err = str(e).lower()
    transient_signals = [
        "429", "rate_limit", "rate limit", "overloaded",
        "500", "502", "503", "504",
        "server_error", "server error", "internal error",
        "timeout", "timed out", "connection",
        "unavailable", "high demand", "resource_exhausted",
    ]
    return any(s in err for s in transient_signals)
