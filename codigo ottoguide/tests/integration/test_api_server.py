from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

# @TASK: Priorizar src local
# @INPUT: Ruta actual del test
# @OUTPUT: Workspace root como primer path de importacion
# @CONTEXT: Evita colision con paquetes src de otros proyectos
# STEP 1: Resolver raiz del proyecto desde tests/integration
# STEP 2: Insertar ruta en sys.path al inicio
# @SECURITY: Reduce riesgo de cargar modulos externos inesperados
# @AI_CONTEXT: Requerido para ejecucion estable en entornos multi-workspace
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Fakes deterministas — sin hardware, ROS, Ollama, audio real ni red
# ---------------------------------------------------------------------------

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
    """Orquestador minimo para validar los endpoints canonicos sin TourOrchestrator real."""

    state_id = "idle"
    _robot_mode = "mock"

    def __init__(self) -> None:
        self.context = _FakeContext()
        self.dispatch_calls: list = []

    async def dispatch_tour(self, plan) -> None:
        self.dispatch_calls.append(plan)

    async def request_interaction(self, audio, *, language="es"):
        pass

    async def emergency_stop(self, *, reason: str = "") -> None:
        pass

    async def build_telemetry_payload(self) -> dict:
        return {}


def _build_canonical_test_app(orchestrator):
    """FastAPI minima respaldada por api.router.router — sin lifespan, sin hardware."""
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


@pytest.fixture
def orchestrator() -> _FakeOrchestrator:
    return _FakeOrchestrator()


@pytest.fixture
def async_client_factory(orchestrator: _FakeOrchestrator):
    """Factory de httpx.AsyncClient conectado via ASGITransport a la app canonica."""

    def _factory() -> httpx.AsyncClient:
        app = _build_canonical_test_app(orchestrator)
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://testserver")

    return _factory


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------

async def test_get_status_idle(async_client_factory) -> None:
    """GET /status debe reportar idle y readiness operativo con backend stub."""
    async with async_client_factory() as client:
        response = await client.get("/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "idle"
    assert payload["operational_ready"] is True
    assert payload["readiness_errors"] == []
    assert payload["navigation_backend_resolved"] == "stub"
    assert payload["navigation_remote_state_unknown"] is False


# ---------------------------------------------------------------------------
# POST /tour/start
# ---------------------------------------------------------------------------

async def test_post_start_tour(
    orchestrator: _FakeOrchestrator, async_client_factory
) -> None:
    """POST /tour/start debe aceptar de forma atomica y devolver el tour_id solicitado."""
    async with async_client_factory() as client:
        response = await client.post(
            "/tour/start",
            json={
                "tour_id": "tour-api-001",
                "waypoints": [
                    {"x": 0.0, "y": 0.0, "yaw_rad": 0.0, "frame_id": "map"},
                ],
            },
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["tour_id"] == "tour-api-001"
    assert len(orchestrator.dispatch_calls) == 1


async def test_post_start_tour_dispatches_expected_plan_once(
    orchestrator: _FakeOrchestrator, async_client_factory
) -> None:
    """POST /tour/start debe despachar exactamente un plan con los waypoints exactos enviados."""
    async with async_client_factory() as client:
        response = await client.post(
            "/tour/start",
            json={
                "tour_id": "tour-api-002",
                "waypoints": [
                    {"x": 1.0, "y": 2.0, "yaw_rad": 0.5, "frame_id": "map"},
                ],
            },
        )

    assert response.status_code == 202
    assert len(orchestrator.dispatch_calls) == 1

    plan = orchestrator.dispatch_calls[0]
    assert plan.tour_id == "tour-api-002"
    assert len(plan.waypoints) == 1
    waypoint = plan.waypoints[0]
    assert waypoint.x == 1.0
    assert waypoint.y == 2.0
    assert waypoint.yaw_rad == 0.5
    assert waypoint.frame_id == "map"


# ---------------------------------------------------------------------------
# Validacion HTTP 422 — limites de NavWaypointDTO via api.schemas
# ---------------------------------------------------------------------------

async def test_waypoint_out_of_bounds_rejected(async_client_factory) -> None:
    """Commit 6: x o y mas alla de ±1000 m deben producir HTTP 422."""
    async with async_client_factory() as client:
        response = await client.post(
            "/tour/start",
            json={
                "tour_id": "oob-tour",
                "waypoints": [{"x": 9999.0, "y": 0.0, "yaw_rad": 0.0, "frame_id": "map"}],
            },
        )
    assert response.status_code == 422, response.text


async def test_waypoint_empty_frame_id_rejected(async_client_factory) -> None:
    """Commit 6: frame_id en blanco debe producir HTTP 422."""
    async with async_client_factory() as client:
        response = await client.post(
            "/tour/start",
            json={
                "tour_id": "frame-tour",
                "waypoints": [{"x": 0.0, "y": 0.0, "yaw_rad": 0.0, "frame_id": "   "}],
            },
        )
    assert response.status_code == 422, response.text


async def test_too_many_waypoints_rejected(async_client_factory) -> None:
    """Commit 6: mas de 50 waypoints deben producir HTTP 422."""
    waypoints = [
        {"x": float(i % 100), "y": 0.0, "yaw_rad": 0.0, "frame_id": "map"}
        for i in range(51)
    ]
    async with async_client_factory() as client:
        response = await client.post(
            "/tour/start",
            json={"tour_id": "big-tour", "waypoints": waypoints},
        )
    assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# Validacion directa de Pydantic — api.schemas.NavWaypointDTO
# ---------------------------------------------------------------------------

def test_schema_waypoint_nan_pydantic_direct() -> None:
    """Commit 6: NavWaypointDTO debe rechazar NaN a nivel del modelo Pydantic."""
    import math
    from api.schemas import NavWaypointDTO
    with pytest.raises(Exception):
        NavWaypointDTO(x=math.nan, y=0.0, yaw_rad=0.0)


def test_schema_waypoint_inf_pydantic_direct() -> None:
    """Commit 6: NavWaypointDTO debe rechazar infinito a nivel del modelo Pydantic."""
    import math
    from api.schemas import NavWaypointDTO
    with pytest.raises(Exception):
        NavWaypointDTO(x=0.0, y=math.inf, yaw_rad=0.0)


def test_schema_waypoint_oob_pydantic_direct() -> None:
    """Commit 6: NavWaypointDTO debe rechazar coordenadas mas alla de ±1000 m."""
    from api.schemas import NavWaypointDTO
    with pytest.raises(Exception):
        NavWaypointDTO(x=1001.0, y=0.0, yaw_rad=0.0)
