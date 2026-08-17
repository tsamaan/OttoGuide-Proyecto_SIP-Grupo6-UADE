"""
@TASK: Validar la extension aditiva de GET /status con los contratos U1
@INPUT: FastAPI minima con api.router, sin lifespan, sin hardware
@OUTPUT: Resultado de pytest: PASSED si la extension es aditiva y conservadora
@CONTEXT: Ejecutar con: python -m pytest tests/integration/test_u1_status_contracts.py -q
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.interaction.runtime_port import (
    INTERACTION_PROTOCOL_VERSION,
    InteractionRuntimeCapabilities,
    InteractionRuntimeHealth,
    InteractionRuntimeState,
)
from src.vision.station_trigger import StationTriggerHealth, StationTriggerState


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


class _IdleOrchestrator:
    state_id = "idle"
    context = _FakeContext()


def _build_minimal_app(orchestrator):
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
    return app


# ---------------------------------------------------------------------------
# 1. Compatibilidad: StatusResponse sin especificar campos nuevos
# ---------------------------------------------------------------------------


def test_status_response_default_construction_is_backward_compatible() -> None:
    from api.schemas import StatusResponse

    response = StatusResponse(state="idle")
    assert response.interaction_runtime.configured is False
    assert response.interaction_runtime.state == "not_configured"
    assert response.station_trigger.configured is False
    assert response.station_trigger.state == "not_configured"


# ---------------------------------------------------------------------------
# 2. GET /status sin ports -> not_configured
# ---------------------------------------------------------------------------


async def test_status_without_ports_reports_not_configured() -> None:
    app = _build_minimal_app(_IdleOrchestrator())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["interaction_runtime"]["configured"] is False
    assert body["interaction_runtime"]["ready"] is False
    assert body["station_trigger"]["configured"] is False
    assert body["station_trigger"]["ready"] is False


# ---------------------------------------------------------------------------
# 3. Ports fake inyectados se mapean correctamente
# ---------------------------------------------------------------------------


class _FakeInteractionRuntime:
    async def health(self) -> InteractionRuntimeHealth:
        return InteractionRuntimeHealth(
            protocol_version=INTERACTION_PROTOCOL_VERSION,
            state=InteractionRuntimeState.READY,
            ready=True,
            capabilities=InteractionRuntimeCapabilities(audio_capture=True),
            last_heartbeat_monotonic_s=12.5,
        )


class _FakeStationTrigger:
    async def health(self) -> StationTriggerHealth:
        return StationTriggerHealth(
            state=StationTriggerState.READY,
            ready=True,
            source="fake-camera",
        )


async def test_status_with_fake_ports_maps_correctly() -> None:
    app = _build_minimal_app(_IdleOrchestrator())
    app.state.interaction_runtime = _FakeInteractionRuntime()
    app.state.station_trigger = _FakeStationTrigger()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["interaction_runtime"]["configured"] is True
    assert body["interaction_runtime"]["state"] == "ready"
    assert body["interaction_runtime"]["ready"] is True
    assert body["interaction_runtime"]["capabilities"]["audio_capture"] is True
    assert body["interaction_runtime"]["last_heartbeat_monotonic_s"] == 12.5

    assert body["station_trigger"]["configured"] is True
    assert body["station_trigger"]["state"] == "ready"
    assert body["station_trigger"]["ready"] is True
    assert body["station_trigger"]["source"] == "fake-camera"


# ---------------------------------------------------------------------------
# 4-6. Degradacion conservadora: timeout, excepcion, metodo ausente
# ---------------------------------------------------------------------------


class _TimeoutInteractionRuntime:
    async def health(self):
        await asyncio.sleep(10)


class _RaisingInteractionRuntime:
    async def health(self):
        raise RuntimeError("boom")


class _NoHealthInteractionRuntime:
    pass


async def test_status_interaction_runtime_health_timeout_does_not_500() -> None:
    app = _build_minimal_app(_IdleOrchestrator())
    app.state.interaction_runtime = _TimeoutInteractionRuntime()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["interaction_runtime"]["state"] == "failed"
    assert body["interaction_runtime"]["ready"] is False
    assert body["interaction_runtime"]["last_error"] == "health_timeout"


async def test_status_interaction_runtime_health_exception_does_not_500() -> None:
    app = _build_minimal_app(_IdleOrchestrator())
    app.state.interaction_runtime = _RaisingInteractionRuntime()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["interaction_runtime"]["state"] == "failed"
    assert body["interaction_runtime"]["last_error"] == "health_error:RuntimeError"


async def test_status_interaction_runtime_missing_health_does_not_500() -> None:
    app = _build_minimal_app(_IdleOrchestrator())
    app.state.interaction_runtime = _NoHealthInteractionRuntime()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["interaction_runtime"]["state"] == "failed"
    assert body["interaction_runtime"]["last_error"] == "health_method_missing"


class _TimeoutStationTrigger:
    async def health(self):
        await asyncio.sleep(10)


async def test_status_station_trigger_health_timeout_does_not_500() -> None:
    app = _build_minimal_app(_IdleOrchestrator())
    app.state.station_trigger = _TimeoutStationTrigger()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["station_trigger"]["state"] == "failed"
    assert body["station_trigger"]["last_error"] == "health_timeout"


# ---------------------------------------------------------------------------
# 7. Capabilities fisicas siguen False salvo declaracion explicita
# ---------------------------------------------------------------------------


async def test_status_capabilities_default_false_unless_declared() -> None:
    app = _build_minimal_app(_IdleOrchestrator())
    app.state.interaction_runtime = _FakeInteractionRuntime()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/status")

    caps = resp.json()["interaction_runtime"]["capabilities"]
    assert caps["audio_capture"] is True
    assert caps["wake_word"] is False
    assert caps["physical_playback"] is False
    assert caps["physical_playback_completion"] is False


# ---------------------------------------------------------------------------
# 8. Campos preexistentes conservan valores y tipos
# ---------------------------------------------------------------------------


async def test_status_preexisting_fields_unchanged() -> None:
    app = _build_minimal_app(_IdleOrchestrator())
    app.state.conversation_runtime_degraded = True
    app.state.conversation_runtime_error = "x"
    app.state.script_loaded = True
    app.state.script_version = "1.0.0"
    app.state.script_waypoint_count = 2
    app.state.script_load_error = None

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/status")

    body = resp.json()
    assert body["conversation_runtime_degraded"] is True
    assert body["conversation_runtime_error"] == "x"
    assert body["script_loaded"] is True
    assert body["script_version"] == "1.0.0"
    assert body["script_waypoint_count"] == 2
    assert isinstance(body["operational_ready"], bool)
    assert isinstance(body["readiness_errors"], list)


# ---------------------------------------------------------------------------
# 9-10. operational_ready y readiness_errors no cambian con/sin nuevos ports
# ---------------------------------------------------------------------------


async def test_operational_ready_identical_with_and_without_new_ports() -> None:
    app_without = _build_minimal_app(_IdleOrchestrator())
    app_with = _build_minimal_app(_IdleOrchestrator())
    app_with.state.interaction_runtime = _FakeInteractionRuntime()
    app_with.state.station_trigger = _FakeStationTrigger()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_without), base_url="http://test") as client:
        resp_without = await client.get("/status")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_with), base_url="http://test") as client:
        resp_with = await client.get("/status")

    assert resp_without.json()["operational_ready"] == resp_with.json()["operational_ready"]
    assert resp_without.json()["readiness_errors"] == resp_with.json()["readiness_errors"]


# ---------------------------------------------------------------------------
# 11-12. No aparecen endpoints nuevos
# ---------------------------------------------------------------------------


def test_no_new_endpoints_registered() -> None:
    from api.router import router

    paths = {route.path for route in router.routes if hasattr(route, "path")}
    forbidden = {"/chat/start", "/tour/start-qr-fsm"}
    assert not (paths & forbidden)
    assert "/telemetry" not in paths


def test_existing_endpoints_still_present() -> None:
    from api.router import router

    paths = {route.path for route in router.routes if hasattr(route, "path")}
    for expected in ("/tour/start", "/tour/pause", "/emergency", "/status"):
        assert expected in paths
