"""
Integration tests for POST /interaction/start and the /status interaction_runtime/
interaction_session extensions added in MVP-R0.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class _FakeNavStatus:
    remote_state_unknown = False
    task_active = False
    action_name = None
    goal_uuid = None


class _FakeNavBridge:
    async def get_status(self):
        return _FakeNavStatus()


class _FakeContext:
    tour_id = None
    current_waypoint_index = 0
    last_error = None


class _FakeOrchestrator:
    def __init__(self, *, state_id="idle", raises=None, interaction_id="standalone:1"):
        self.state_id = state_id
        self.context = _FakeContext()
        self._raises = raises
        self._interaction_id = interaction_id
        self.calls: list[tuple[str, float]] = []

    @property
    def standalone_interaction_session(self):
        return {"session_id": None, "state": "idle", "last_event": None}

    async def start_standalone_interaction(self, *, locale, timeout_s):
        self.calls.append((locale, timeout_s))
        if self._raises is not None:
            raise self._raises
        return self._interaction_id


def _build_app(orchestrator, *, interaction_runtime=None, requested="disabled", mock=False):
    from fastapi import FastAPI
    from api.router import router

    app = FastAPI()
    app.include_router(router)

    app.state.orchestrator = orchestrator
    app.state.nav_bridge = _FakeNavBridge()
    app.state.navigation_backend_requested = "stub"
    app.state.navigation_backend_resolved = "stub"
    app.state.navigation_started = False
    app.state.navigation_stub_tours_allowed = True
    app.state.factory_rest_client = None
    app.state.interaction_runtime = interaction_runtime
    app.state.interaction_runtime_requested = requested
    app.state.interaction_runtime_mock = mock
    app.state.interaction_runtime_termination = None
    return app


@pytest.mark.asyncio
async def test_interaction_start_503_when_runtime_disabled():
    app = _build_app(_FakeOrchestrator(), interaction_runtime=None, requested="disabled")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/interaction/start", json={"locale": "es", "timeout_s": 10.0})

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_interaction_start_202_when_runtime_ready():
    orchestrator = _FakeOrchestrator(state_id="idle")
    app = _build_app(
        orchestrator,
        interaction_runtime=object(),
        requested="cxx_jsonl_mock",
        mock=True,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/interaction/start", json={"locale": "es", "timeout_s": 10.0})

    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] is True
    assert body["interaction_id"] == "standalone:1"
    assert body["runtime_backend"] == "cxx_jsonl_mock"
    assert body["runtime_mock"] is True
    assert orchestrator.calls == [("es", 10.0)]


@pytest.mark.asyncio
async def test_interaction_start_409_when_fsm_not_idle():
    orchestrator = _FakeOrchestrator(state_id="navigating")
    app = _build_app(orchestrator, interaction_runtime=object(), requested="cxx_jsonl_mock", mock=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/interaction/start", json={"locale": "es", "timeout_s": 10.0})

    assert response.status_code == 409
    assert orchestrator.calls == []


@pytest.mark.asyncio
async def test_interaction_start_409_when_already_active():
    orchestrator = _FakeOrchestrator(
        state_id="idle",
        raises=RuntimeError("start_standalone_interaction() rechazado: ya existe una interaccion activa."),
    )
    app = _build_app(orchestrator, interaction_runtime=object(), requested="cxx_jsonl_mock", mock=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/interaction/start", json={"locale": "es", "timeout_s": 10.0})

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_interaction_start_422_on_invalid_timeout():
    app = _build_app(_FakeOrchestrator(), interaction_runtime=object(), requested="cxx_jsonl_mock", mock=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/interaction/start", json={"locale": "es", "timeout_s": -1.0})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_status_reports_mock_true_and_physical_false_for_cxx_mock():
    app = _build_app(_FakeOrchestrator(), interaction_runtime=None, requested="cxx_jsonl_mock", mock=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/status")

    assert response.status_code == 200
    body = response.json()
    assert "interaction_session" in body
    assert body["interaction_session"]["state"] == "idle"
    assert body["interaction_session"]["active"] is False


@pytest.mark.asyncio
async def test_status_interaction_runtime_not_configured_when_no_runtime():
    app = _build_app(_FakeOrchestrator(), interaction_runtime=None, requested="disabled", mock=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/status")

    assert response.status_code == 200
    body = response.json()
    assert body["interaction_runtime"]["configured"] is False
    assert body["interaction_runtime"]["mock"] is False
    assert body["interaction_runtime"]["physical"] is False
