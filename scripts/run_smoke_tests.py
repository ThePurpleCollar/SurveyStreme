"""Run all smoke test scripts without requiring pytest."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    tests = sorted((root / "tests").glob("smoke_test_*.py"))
    if not tests:
        print("No smoke tests found.")
        return 1

    for test in tests:
        print(f"RUN {test.relative_to(root)}", flush=True)
        result = subprocess.run([sys.executable, str(test)], cwd=root)
        if result.returncode != 0:
            print(f"FAILED {test.name} ({result.returncode})")
            return result.returncode

    print(f"ALL {len(tests)} SMOKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
