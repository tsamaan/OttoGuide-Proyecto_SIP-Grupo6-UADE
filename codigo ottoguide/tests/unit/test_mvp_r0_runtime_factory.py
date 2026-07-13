from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from src.interaction.jsonl_worker_supervisor import JsonlInteractionWorkerSupervisor
from src.interaction.runtime_factory import build_interaction_runtime


def _settings(**overrides):
    base = dict(
        INTERACTION_RUNTIME_BACKEND="disabled",
        INTERACTION_WORKER_PATH="",
        INTERACTION_STARTUP_TIMEOUT_S=3.0,
        INTERACTION_HEARTBEAT_TIMEOUT_S=5.0,
        INTERACTION_SHUTDOWN_TIMEOUT_S=2.0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_disabled_backend_returns_none():
    settings = _settings(INTERACTION_RUNTIME_BACKEND="disabled")
    assert build_interaction_runtime(settings) is None


def test_cxx_jsonl_mock_builds_supervisor_without_starting():
    settings = _settings(
        INTERACTION_RUNTIME_BACKEND="cxx_jsonl_mock",
        INTERACTION_WORKER_PATH="/tmp/fake_worker",
    )
    runtime = build_interaction_runtime(settings)
    assert isinstance(runtime, JsonlInteractionWorkerSupervisor)
    # @SECURITY: construction must never start a process.
    assert runtime._process is None


def test_unknown_backend_raises_fail_closed():
    settings = _settings(INTERACTION_RUNTIME_BACKEND="something_else")
    with pytest.raises(ValueError, match="unknown_backend"):
        build_interaction_runtime(settings)


def test_argv_derived_from_worker_path_as_single_arg():
    settings = _settings(
        INTERACTION_RUNTIME_BACKEND="cxx_jsonl_mock",
        INTERACTION_WORKER_PATH="/opt/otto/worker_bin",
    )
    runtime = build_interaction_runtime(settings)
    assert runtime._config.argv == ("/opt/otto/worker_bin",)
