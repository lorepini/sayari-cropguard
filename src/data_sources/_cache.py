"""
Tiny in-process TTL cache for HTTP fetchers.

Open-Meteo (and similar free APIs) rate-limit by IP. The dashboard refreshes
every few minutes and each refresh used to fan out into ~10 independent
fetches (forecast, ensemble, historical archive, drought SPI…). On Render —
which has a single egress IP — that hit Open-Meteo's free-tier 429 quickly.

This wrapper caches each (function, args) pair for `ttl_seconds`. The cache
is per-process (resets on Render redeploy / WSGI worker restart, which is
fine — we just need to dampen the per-refresh fan-out).

Pickling not required: pandas DataFrames live in memory unchanged.
"""
from __future__ import annotations

import threading
import time
from functools import wraps
from typing import Any, Callable


def ttl_cache(ttl_seconds: int):
    """Decorator: cache a function's return value for `ttl_seconds`.

    Hashable args/kwargs only — DataFrames/lists as kwargs would TypeError.
    Network fetchers in this project all take simple scalars (lat, lon,
    dates) so this is fine.
    """
    def decorator(fn: Callable[..., Any]):
        cache: dict[tuple, tuple[float, Any]] = {}
        lock = threading.Lock()

        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.time()
            with lock:
                hit = cache.get(key)
                if hit is not None and (now - hit[0]) < ttl_seconds:
                    return hit[1]
            value = fn(*args, **kwargs)
            with lock:
                cache[key] = (now, value)
            return value

        wrapper.cache_clear = lambda: cache.clear()  # type: ignore[attr-defined]
        return wrapper
    return decorator
