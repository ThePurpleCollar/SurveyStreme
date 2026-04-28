import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.network_config import sanitize_proxy_environment


original = {k: os.environ.get(k) for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")}
try:
    os.environ["HTTP_PROXY"] = "http://127.0.0.1:9"
    os.environ["HTTPS_PROXY"] = "http://localhost:9"
    os.environ["ALL_PROXY"] = "http://proxy.company.local:8080"

    removed = sanitize_proxy_environment()

    assert removed["HTTP_PROXY"] == "http://127.0.0.1:9"
    assert removed["HTTPS_PROXY"] == "http://localhost:9"
    assert "HTTP_PROXY" not in os.environ
    assert "HTTPS_PROXY" not in os.environ
    assert os.environ["ALL_PROXY"] == "http://proxy.company.local:8080"
finally:
    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

print("ALL NETWORK CONFIG TESTS PASSED")
