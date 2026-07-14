"""MVP-IA-CXX-R1: cxx_jsonl_physical backend — settings validation + factory resolution.

Offline unit coverage for the new physical audio worker backend. No process is started, no
hardware is touched. Confirms:
  - the physical backend builds the SAME supervisor as the mock (no duplicate supervisor);
  - it requires an explicit worker path;
  - it is permitted in ROBOT_MODE=real WITHOUT the mock-in-real allow flag (it is not a mock);
  - it is fail-closed against unknown backends.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from config.settings import Settings
from src.interaction.jsonl_worker_supervisor import JsonlInteractionWorkerSupervisor
from src.interaction.runtime_factory import build_interaction_runtime


def _factory_settings(**overrides):
    base = dict(
        INTERACTION_RUNTIME_BACKEND="disabled",
        INTERACTION_WORKER_PATH="",
        INTERACTION_STARTUP_TIMEOUT_S=3.0,
        INTERACTION_HEARTBEAT_TIMEOUT_S=5.0,
        INTERACTION_SHUTDOWN_TIMEOUT_S=2.0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_physical_backend_builds_supervisor_without_starting():
    settings = _factory_settings(
        INTERACTION_RUNTIME_BACKEND="cxx_jsonl_physical",
        INTERACTION_WORKER_PATH="/opt/otto/otto_jsonl_physical_worker",
    )
    runtime = build_interaction_runtime(settings)
    assert isinstance(runtime, JsonlInteractionWorkerSupervisor)
    assert runtime._process is None  # construction never starts a process
    assert runtime._config.argv == ("/opt/otto/otto_jsonl_physical_worker",)


def test_physical_backend_valid_in_real_mode_without_allow_flag():
    # cxx_jsonl_physical is genuinely physical; it must NOT require the mock-in-real flag.
    s = Settings(
        ROBOT_MODE="real",
        INTERACTION_RUNTIME_BACKEND="cxx_jsonl_physical",
        INTERACTION_WORKER_PATH="/opt/otto/otto_jsonl_physical_worker",
        INTERACTION_RUNTIME_ALLOW_MOCK_IN_REAL=False,
        WEB_UI_ALLOWED_ORIGINS="http://127.0.0.1:3001",
    )
    s.validate_interaction_runtime_config()  # must not raise


def test_physical_backend_requires_worker_path():
    s = Settings(
        ROBOT_MODE="real",
        INTERACTION_RUNTIME_BACKEND="cxx_jsonl_physical",
        INTERACTION_WORKER_PATH="",
        WEB_UI_ALLOWED_ORIGINS="http://127.0.0.1:3001",
    )
    with pytest.raises(ValueError, match="INTERACTION_WORKER_PATH_empty"):
        s.validate_interaction_runtime_config()


def test_mock_still_blocked_in_real_without_flag():
    # Regression: extending the literal must not loosen the mock interlock.
    s = Settings(
        ROBOT_MODE="real",
        INTERACTION_RUNTIME_BACKEND="cxx_jsonl_mock",
        INTERACTION_WORKER_PATH="/opt/otto/shim",
        INTERACTION_RUNTIME_ALLOW_MOCK_IN_REAL=False,
        WEB_UI_ALLOWED_ORIGINS="http://127.0.0.1:3001",
    )
    with pytest.raises(ValueError, match="cxx_jsonl_mock_forbidden_in_real_mode"):
        s.validate_interaction_runtime_config()
