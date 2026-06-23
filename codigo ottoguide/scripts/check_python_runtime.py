#!/usr/bin/env python3
"""Python runtime compatibility preflight for OttoGuide.

Checks that the interpreter version meets the minimum requirement declared in
pyproject.toml (Python >= 3.10). Fails closed: on an unsupported interpreter
the script exits with status 1 so any caller — preflight_check.sh, CI gate,
or a shell one-liner — sees a definite failure rather than a silent pass that
could allow the application to start and crash unpredictably at import time.

Exit codes:
  0  PYTHON_RUNTIME_COMPATIBLE=true   (decision=PASS)
  1  PYTHON_RUNTIME_COMPATIBLE=false  (decision=BLOCKED)

JSON output (stdout) is always emitted regardless of the decision, so
automated callers can parse the structured result while humans read the
exit code.
"""
from __future__ import annotations

import json
import sys

REQUIRED_MAJOR = 3
REQUIRED_MINOR = 10
REQUIRED_VERSION = (REQUIRED_MAJOR, REQUIRED_MINOR)


def check_python_runtime(version_info=None) -> dict:
    """Return a structured compatibility result.

    version_info defaults to sys.version_info; callers may pass a
    synthetic version (e.g. a namedtuple with major/minor/micro) so tests
    can simulate any Python version without spawning a different interpreter.
    """
    if version_info is None:
        version_info = sys.version_info
    compatible = (version_info.major, version_info.minor) >= REQUIRED_VERSION
    return {
        "PYTHON_RUNTIME_COMPATIBLE": compatible,
        "decision": "PASS" if compatible else "BLOCKED",
        "python_version": f"{version_info.major}.{version_info.minor}.{version_info.micro}",
        "required_version": f"{REQUIRED_MAJOR}.{REQUIRED_MINOR}",
    }


if __name__ == "__main__":
    result = check_python_runtime()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["PYTHON_RUNTIME_COMPATIBLE"] else 1)
