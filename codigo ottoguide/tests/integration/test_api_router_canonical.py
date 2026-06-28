"""
Integration tests for the canonical OttoGuide API: api.router (NOT src.api.server).

Demonstrates:
  5.1  main.create_app() includes endpoints from api.router
  5.2  POST /tour/start awaits dispatch_tour() before responding
  5.3  Two concurrent starts: only one is ever accepted
  5.4  POST /tour/pause awaits request_interaction() before responding
       POST /tour/pause + TransitionNotAllowed -> HTTP 409
  misc accepted field is JSON boolean true, not a string
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from statemachine.exceptions import TransitionNotAllowed


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class _FakeTransitionNotAllowed(TransitionNotAllowed):
    """Instantiable subclass that satisfies isinstance checks in the router."""
    def __init__(self):
        Exception.__init__(self, "fake transition not allowed")


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


def _build_minimal_app(orchestrator):
    """Minimal FastAPI backed by api.router.router — no lifespan, no hardware."""
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


_VALID_PAYLOAD = {
    "tour_id": "t-canonical",
    "waypoints": [{"x": 0.0, "y": 0.0, "yaw_rad": 0.0, "frame_id": "map"}],
}


# ---------------------------------------------------------------------------
# 5.1 — Wiring: main.create_app() uses api.router
# ---------------------------------------------------------------------------

def test_canonical_wiring():
    """Routes /tour/start, /tour/pause, /status are registered by main.create_app()
    and their handlers belong to the api.router module."""
    import main

    app = main.create_app()

    def _collect_routes(routes):
        # FastAPI (>=0.100) wraps include_router() in _IncludedRouter objects which
        # store their routes in .original_router rather than as direct .routes.
        result = {}
        for r in routes:
            if hasattr(r, "path") and hasattr(r, "endpoint"):
                result[r.path] = r.endpoint
            if hasattr(r, "routes"):
                result.update(_collect_routes(r.routes))
            if hasattr(r, "original_router") and hasattr(r.original_router, "routes"):
                result.update(_collect_routes(r.original_router.routes))
        return result

    route_map = _collect_routes(app.routes)

    for path in ("/tour/start", "/tour/pause", "/status"):
        assert path in route_map, f"Route {path} not registered in create_app()"
        mod = route_map[path].__module__
        assert mod == "api.router", (
            f"Handler for {path} is in '{mod}', expected 'api.router'"
        )


# ---------------------------------------------------------------------------
# 5.1b — GET /status exposes conversation/script observability fields (Section 10)
# ---------------------------------------------------------------------------

class _IdleOrchestrator:
    state_id = "idle"
    context = _FakeContext()


@pytest.mark.asyncio
async def test_status_exposes_conversation_and_script_observability_fields():
    """/status must surface conversation_runtime_error and the script_* fields straight
    from app.state, defaulting safely when boot never set them (mock/sim degraded path)."""
    app = _build_minimal_app(_IdleOrchestrator())
    app.state.conversation_runtime_degraded = True
    app.state.conversation_runtime_error = "RuntimeError: ollama unreachable"
    app.state.script_loaded = False
    app.state.script_version = None
    app.state.script_waypoint_count = 0
    app.state.script_load_error = "SCRIPT_NOT_FOUND:/data/mvp_tour_script.json"

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/status")

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_runtime_degraded"] is True
    assert body["conversation_runtime_error"] == "RuntimeError: ollama unreachable"
    assert body["script_loaded"] is False
    assert body["script_version"] is None
    assert body["script_waypoint_count"] == 0
    assert body["script_load_error"] == "SCRIPT_NOT_FOUND:/data/mvp_tour_script.json"


@pytest.mark.asyncio
async def test_status_reports_script_loaded_successfully():
    """/status must report script_loaded=True with version/waypoint_count once the boot
    sequence has populated app.state after a successful load_script_from_file()."""
    app = _build_minimal_app(_IdleOrchestrator())
    app.state.conversation_runtime_degraded = False
    app.state.conversation_runtime_error = None
    app.state.script_loaded = True
    app.state.script_version = "1.2.0"
    app.state.script_waypoint_count = 5
    app.state.script_load_error = None

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/status")

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_runtime_degraded"] is False
    assert body["script_loaded"] is True
    assert body["script_version"] == "1.2.0"
    assert body["script_waypoint_count"] == 5
    assert body["script_load_error"] is None


# ---------------------------------------------------------------------------
# 5.2 — POST /tour/start awaits dispatch_tour()
# ---------------------------------------------------------------------------

class _DispatchControlledOrchestrator:
    state_id = "idle"
    _robot_mode = "mock"
    context = _FakeContext()

    def __init__(self):
        self.invoked = asyncio.Event()
        self._release = asyncio.Event()
        self.dispatch_calls: list = []

    async def dispatch_tour(self, plan):
        self.dispatch_calls.append(plan)
        self.invoked.set()
        await self._release.wait()

    async def emergency_stop(self, *, reason=""):
        pass

    async def build_telemetry_payload(self):
        return {}


async def test_start_awaits_dispatch_tour():
    """The endpoint must not respond until dispatch_tour() returns."""
    orch = _DispatchControlledOrchestrator()
    app = _build_minimal_app(orch)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        task = asyncio.create_task(client.post("/tour/start", json=_VALID_PAYLOAD))

        await asyncio.wait_for(orch.invoked.wait(), timeout=2.0)

        # dispatch_tour is still blocked — HTTP response must not be ready yet
        assert not task.done(), (
            "POST /tour/start returned before dispatch_tour() completed"
        )
        assert len(orch.dispatch_calls) == 1

        orch._release.set()
        resp = await asyncio.wait_for(task, timeout=2.0)

    assert resp.status_code == 202
    data = resp.json()
    assert data["accepted"] is True
    assert data["tour_id"] == "t-canonical"


# ---------------------------------------------------------------------------
# 5.3 — Concurrent starts: both reach dispatch, only one accepted
# ---------------------------------------------------------------------------

class _AtomicOrchestrator:
    """Barrier-based fake that forces both concurrent calls into dispatch_tour()
    before either competes for the single-acceptance reservation.

    Design:
    - state_id is always "idle" so both requests pass the readiness gate.
    - _entry_lock + _entry_count tracks arrivals atomically.
    - When the second call arrives it fires _both_entered (barrier).
    - Both calls wait on _both_entered before reaching _reserve_lock.
    - _reserve_lock + _accepted allow exactly one plan; the second raises
      TransitionNotAllowed.
    """

    state_id = "idle"   # fixed: both requests must pass readiness without 503
    _robot_mode = "mock"
    context = _FakeContext()

    def __init__(self):
        self._entry_lock = asyncio.Lock()
        self._entry_count = 0
        self._both_entered = asyncio.Event()

        self._reserve_lock = asyncio.Lock()
        self._accepted = False

        self.dispatch_entry_count = 0
        self.accepted_plans: list = []

    async def dispatch_tour(self, plan):
        # Step 1: register entry under the entry lock (no yields inside)
        async with self._entry_lock:
            self._entry_count += 1
            self.dispatch_entry_count += 1
            if self._entry_count == 2:
                self._both_entered.set()

        # Step 2: barrier — wait until both calls are inside before competing
        await asyncio.wait_for(self._both_entered.wait(), timeout=2.0)

        # Step 3: compete for single-acceptance reservation
        async with self._reserve_lock:
            if self._accepted:
                raise _FakeTransitionNotAllowed()
            self._accepted = True
            self.accepted_plans.append(plan)

    async def emergency_stop(self, *, reason=""):
        pass

    async def build_telemetry_payload(self):
        return {}


async def test_concurrent_start_single_acceptance():
    """Two concurrent POST /tour/start requests must both reach dispatch_tour()
    and produce exactly HTTP 202 + HTTP 409 — never 503, never two acceptances."""
    orch = _AtomicOrchestrator()
    app = _build_minimal_app(orch)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r1, r2 = await asyncio.wait_for(
            asyncio.gather(
                client.post("/tour/start", json=_VALID_PAYLOAD),
                client.post("/tour/start", json=_VALID_PAYLOAD),
            ),
            timeout=5.0,
        )

    # Both must have entered dispatch_tour (barrier enforces this)
    assert orch.dispatch_entry_count == 2, (
        f"Expected both calls to reach dispatch_tour(), got {orch.dispatch_entry_count}"
    )

    # Exactly one plan accepted inside dispatch_tour
    assert len(orch.accepted_plans) == 1, (
        f"Expected 1 accepted plan, got {len(orch.accepted_plans)}"
    )

    # HTTP layer: exactly 202 + 409, never 503
    assert sorted([r1.status_code, r2.status_code]) == [202, 409], (
        f"Expected [202, 409], got {sorted([r1.status_code, r2.status_code])}"
    )

    # Exactly one response carries accepted=true
    accepted_true_count = sum(
        1 for r in (r1, r2) if r.json().get("accepted") is True
    )
    assert accepted_true_count == 1, (
        f"Expected exactly 1 accepted=true, got {accepted_true_count}"
    )

    # The 409 response must not carry accepted=true
    fail_resp = next(r for r in (r1, r2) if r.status_code == 409)
    assert fail_resp.json().get("accepted") is not True, (
        "409 response must not contain accepted=true"
    )


# ---------------------------------------------------------------------------
# 5.4 — POST /tour/pause awaits request_interaction()
# ---------------------------------------------------------------------------

class _PauseControlledOrchestrator:
    state_id = "navigating"  # CHANGE D: endpoint requires NAVIGATING state
    _robot_mode = "mock"
    context = _FakeContext()

    def __init__(self):
        self.invoked = asyncio.Event()
        self._release = asyncio.Event()
        self.interaction_calls: list = []

    async def request_interaction(self, audio, *, language="es"):
        self.interaction_calls.append((audio, language))
        self.invoked.set()
        await self._release.wait()

    async def dispatch_tour(self, plan):
        pass

    async def emergency_stop(self, *, reason=""):
        pass

    async def build_telemetry_payload(self):
        return {}


async def test_pause_awaits_interaction():
    """The endpoint must not respond until request_interaction() returns."""
    orch = _PauseControlledOrchestrator()
    app = _build_minimal_app(orch)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        task = asyncio.create_task(
            client.post("/tour/pause", json={"language": "es"})
        )

        await asyncio.wait_for(orch.invoked.wait(), timeout=2.0)

        assert not task.done(), (
            "POST /tour/pause returned before request_interaction() completed"
        )
        assert len(orch.interaction_calls) == 1

        orch._release.set()
        resp = await asyncio.wait_for(task, timeout=2.0)

    assert resp.status_code == 202
    assert resp.json()["accepted"] is True


# ---------------------------------------------------------------------------
# 5.4 — POST /tour/pause + invalid transition -> HTTP 409
# ---------------------------------------------------------------------------

class _RejectingOrchestrator:
    state_id = "navigating"  # CHANGE D: must be navigating to reach request_interaction
    _robot_mode = "mock"
    context = _FakeContext()

    async def request_interaction(self, audio, *, language="es"):
        raise _FakeTransitionNotAllowed()

    async def dispatch_tour(self, plan):
        pass

    async def emergency_stop(self, *, reason=""):
        pass

    async def build_telemetry_payload(self):
        return {}


async def test_pause_transition_not_allowed_returns_409():
    """TransitionNotAllowed in request_interaction must yield HTTP 409."""
    orch = _RejectingOrchestrator()
    app = _build_minimal_app(orch)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/tour/pause", json={"language": "es"})

    assert resp.status_code == 409, (
        f"Expected 409 for invalid transition, got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# accepted is JSON boolean true (not string "true" / "True" / 1)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 5.4.D — POST /tour/pause: explicit state guard added by CHANGE D
# ---------------------------------------------------------------------------

class _StateOrchestrator:
    """Fake orchestrator with configurable state_id for state-guard tests."""
    _robot_mode = "mock"
    context = _FakeContext()

    def __init__(self, state: str):
        self.state_id = state

    async def request_interaction(self, audio, *, language="es"):
        pass

    async def dispatch_tour(self, plan):
        pass

    async def emergency_stop(self, *, reason=""):
        pass

    async def build_telemetry_payload(self):
        return {}


async def test_pause_idle_state_returns_409():
    """POST /tour/pause from IDLE must return 409 — explicit state guard (CHANGE D)."""
    orch = _StateOrchestrator("idle")
    app = _build_minimal_app(orch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/tour/pause", json={"language": "es"})
    assert resp.status_code == 409


async def test_pause_interacting_state_returns_409():
    """POST /tour/pause from INTERACTING must return 409 — explicit state guard (CHANGE D)."""
    orch = _StateOrchestrator("interacting")
    app = _build_minimal_app(orch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/tour/pause", json={"language": "es"})
    assert resp.status_code == 409


async def test_pause_emergency_state_returns_409():
    """POST /tour/pause from EMERGENCY must return 409 — explicit state guard (CHANGE D)."""
    orch = _StateOrchestrator("emergency")
    app = _build_minimal_app(orch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/tour/pause", json={"language": "es"})
    assert resp.status_code == 409


async def test_pause_navigating_state_returns_202():
    """POST /tour/pause from NAVIGATING must return 202 — correct state (CHANGE D)."""
    orch = _PauseControlledOrchestrator()
    app = _build_minimal_app(orch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        orch._release.set()
        resp = await asyncio.wait_for(
            client.post("/tour/pause", json={"language": "es"}),
            timeout=3.0,
        )
    assert resp.status_code == 202


# ---------------------------------------------------------------------------
# G-03 — Real TourOrchestrator (AsyncEngine) concurrent dispatch atomicity
# ---------------------------------------------------------------------------

async def test_real_orchestrator_concurrent_dispatch_is_atomic():
    """G-03: Real TourOrchestrator with AsyncEngine serialises concurrent dispatch_tour().

    Unlike _AtomicOrchestrator (a hand-rolled barrier fake), this test uses the
    actual python-statemachine FSM to prove that two concurrent dispatch_tour()
    calls produce exactly one success and one rejection — no barrier fake needed.
    """
    from unittest.mock import AsyncMock, MagicMock
    from src.core import TourOrchestrator, TourPlan
    from src.navigation.models import NavWaypoint

    hw = MagicMock()
    hw.move = AsyncMock()
    hw.damp = AsyncMock()

    nav = MagicMock()
    nav.navigate_to_waypoints = AsyncMock(return_value=False)
    nav.cancel_navigation = AsyncMock()
    nav.get_status = AsyncMock(return_value=MagicMock(
        remote_state_unknown=False,
        task_active=False,
        last_result=MagicMock(succeeded=False),
    ))
    nav.inject_absolute_pose = AsyncMock()
    nav.start = AsyncMock()
    nav.close = AsyncMock()

    cm = MagicMock()
    cm.process_interaction = AsyncMock(return_value=MagicMock(
        answer_text="", source_pipeline="stub", audio_stream_ready=False,
    ))
    cm.close = MagicMock()
    cm.loaded_script = None

    vp = MagicMock()
    vp.close = MagicMock()
    vp.get_next_estimate = AsyncMock(return_value=None)

    orchestrator = TourOrchestrator(
        hardware_api=hw,
        nav_bridge=nav,
        conversation_manager=cm,
        vision_processor=vp,
        robot_mode="mock",
    )
    await orchestrator.activate_initial_state()

    plan = TourPlan(
        waypoints=[NavWaypoint(x=0.0, y=0.0, yaw_rad=0.0, frame_id="map")],
        tour_id="g03-concurrent",
    )

    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                orchestrator.dispatch_tour(plan),
                orchestrator.dispatch_tour(plan),
                return_exceptions=True,
            ),
            timeout=5.0,
        )
    finally:
        try:
            await asyncio.wait_for(
                orchestrator.emergency_stop(reason="g03-cleanup"),
                timeout=2.0,
            )
        except Exception:
            pass

    successes = [r for r in results if not isinstance(r, BaseException)]
    failures = [r for r in results if isinstance(r, BaseException)]

    assert len(successes) == 1, (
        f"G-03: expected exactly 1 dispatch_tour() to succeed, got {len(successes)}; "
        f"results={results}"
    )
    assert len(failures) == 1, (
        f"G-03: expected 1 rejection, got {len(failures)}; results={results}"
    )


async def test_start_accepted_is_json_boolean():
    """accepted in POST /tour/start response must be JSON boolean true, not a string."""

    class _NullOrchestrator:
        state_id = "idle"
        _robot_mode = "mock"
        context = _FakeContext()

        async def dispatch_tour(self, plan):
            pass

        async def emergency_stop(self, *, reason=""):
            pass

        async def build_telemetry_payload(self):
            return {}

    orch = _NullOrchestrator()
    app = _build_minimal_app(orch)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/tour/start", json=_VALID_PAYLOAD)

    assert resp.status_code == 202
    raw = resp.json()
    assert raw["accepted"] is True, (
        f"accepted must be bool True, got {raw['accepted']!r} "
        f"(type: {type(raw['accepted']).__name__})"
    )
