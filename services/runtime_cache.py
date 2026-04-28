"""Process-local caches for expensive deterministic work.

The cache is intentionally in-memory only. It avoids repeating identical LLM
and export work during a Streamlit process, while keeping source documents out
of persistent storage.
"""

from __future__ import annotations

from collections import OrderedDict
import copy
import hashlib
import json
import os
import threading
from typing import Any


_MAX_ITEMS = int(os.getenv("SURVEY_STREAM_RUNTIME_CACHE_MAX", "256"))
_LOCK = threading.RLock()
_CACHES: dict[str, OrderedDict[str, Any]] = {}


def stable_cache_key(*parts: Any) -> str:
    """Return a stable hash for JSON-like cache key parts."""
    payload = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_runtime_cache(namespace: str, key: str) -> tuple[bool, Any]:
    """Return ``(True, value)`` on hit, ``(False, None)`` on miss."""
    with _LOCK:
        cache = _CACHES.get(namespace)
        if not cache or key not in cache:
            return False, None
        value = cache.pop(key)
        cache[key] = value
        return True, copy.deepcopy(value)


def set_runtime_cache(namespace: str, key: str, value: Any) -> None:
    """Store a value in a bounded LRU cache."""
    with _LOCK:
        cache = _CACHES.setdefault(namespace, OrderedDict())
        if key in cache:
            cache.pop(key)
        cache[key] = copy.deepcopy(value)
        while len(cache) > _MAX_ITEMS:
            cache.popitem(last=False)


def runtime_cache_stats() -> dict[str, int]:
    """Expose cache sizes for diagnostics/tests."""
    with _LOCK:
        return {name: len(cache) for name, cache in _CACHES.items()}
