import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.runtime_cache import (
    get_runtime_cache,
    runtime_cache_stats,
    set_runtime_cache,
    stable_cache_key,
)


key1 = stable_cache_key("model", {"b": 2, "a": 1})
key2 = stable_cache_key("model", {"a": 1, "b": 2})
assert key1 == key2

set_runtime_cache("smoke", key1, {"items": [1, 2]})
hit, value = get_runtime_cache("smoke", key2)
assert hit
assert value == {"items": [1, 2]}

value["items"].append(3)
hit, value2 = get_runtime_cache("smoke", key2)
assert hit
assert value2 == {"items": [1, 2]}
assert runtime_cache_stats()["smoke"] == 1

print("ALL RUNTIME CACHE TESTS PASSED")
