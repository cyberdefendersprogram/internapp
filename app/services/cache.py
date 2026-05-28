"""In-memory TTL cache for reducing Google Sheets API calls."""

import logging
from functools import wraps
from time import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Global cache storage: {key: (value, expires_at)}
_cache: dict[str, tuple[Any, float]] = {}


def cached(ttl_seconds: int, prefix: str = ""):
    """
    Decorator to cache function results with TTL.

    Args:
        ttl_seconds: Time-to-live in seconds
        prefix: Optional prefix for cache key (used for invalidation)
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Build cache key from function name, args, and kwargs
            key_prefix = prefix or func.__name__
            key_parts = [key_prefix, func.__name__]
            # For methods, args[0] is self - we skip it to avoid object identity issues
            start_idx = 1 if args and hasattr(args[0], func.__name__) else 0
            key_parts.extend(str(arg) for arg in args[start_idx:])
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            cache_key = ":".join(key_parts)

            now = time()

            # Check cache
            if cache_key in _cache:
                value, expires_at = _cache[cache_key]
                if now < expires_at:
                    logger.debug("Cache hit: %s", cache_key)
                    return value
                else:
                    del _cache[cache_key]

            # Cache miss, call function
            logger.debug("Cache miss: %s", cache_key)
            result = func(*args, **kwargs)

            # Store in cache
            _cache[cache_key] = (result, now + ttl_seconds)

            return result

        # Attach cache key generator for manual invalidation
        wrapper.cache_prefix = prefix or func.__name__
        return wrapper

    return decorator


def invalidate(prefix: str) -> int:
    """
    Invalidate all cache entries matching prefix.

    Returns:
        Number of entries invalidated
    """
    keys_to_delete = [k for k in _cache if k.startswith(prefix)]
    for key in keys_to_delete:
        del _cache[key]

    if keys_to_delete:
        logger.debug("Invalidated %d cache entries with prefix: %s", len(keys_to_delete), prefix)

    return len(keys_to_delete)


def invalidate_all() -> int:
    """Clear entire cache. Returns number of entries cleared."""
    count = len(_cache)
    _cache.clear()
    logger.debug("Cleared entire cache: %d entries", count)
    return count


def get_cache_stats() -> dict:
    """Get cache statistics for debugging."""
    now = time()
    total = len(_cache)
    expired = sum(1 for _, (_, exp) in _cache.items() if exp < now)

    return {
        "total_entries": total,
        "expired_entries": expired,
        "active_entries": total - expired,
    }
