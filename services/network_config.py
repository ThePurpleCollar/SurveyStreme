"""Network environment safeguards for LLM calls."""

from __future__ import annotations

import os
from urllib.parse import urlparse


_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def _is_blocked_local_proxy(value: str) -> bool:
    if not value:
        return False
    parsed = urlparse(value if "://" in value else f"http://{value}")
    host = (parsed.hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"} and parsed.port == 9


def sanitize_proxy_environment() -> dict[str, str]:
    """Remove known dead local proxy values from this process.

    Some sandboxed shells inject 127.0.0.1:9 as a sink proxy. If Streamlit is
    launched from that shell, Vertex/OpenAI clients inherit it and LLM calls
    fail before reaching the real LiteLLM endpoint. Real corporate proxy values
    are left untouched.
    """
    removed = {}
    for key in _PROXY_ENV_KEYS:
        value = os.environ.get(key, "")
        if _is_blocked_local_proxy(value):
            removed[key] = value
            os.environ.pop(key, None)
    return removed
