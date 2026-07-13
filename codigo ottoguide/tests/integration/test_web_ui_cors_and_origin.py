"""
Integration tests for the web UI hardening added for pilar-web integration:
  - CORSMiddleware on main.create_app() (allowed/rejected origin, wildcard rejected in real mode)
  - Manual Origin validation on WS /ws/telemetry
  - "/" and "/dashboard" redirect to WEB_UI_PUBLIC_URL, or 503 explicit if unset (WEB-R6:
    the legacy static dashboard is no longer a silent fallback; see /dashboard-legacy)

These tests call main.create_app() directly via httpx.ASGITransport WITHOUT triggering the
FastAPI lifespan (no lifespan="on"), so no hardware/orchestrator boot is exercised — only the
app-construction-time wiring (CORSMiddleware, dashboard route) and the WS handler's manual
Origin check, which reads config.settings.get_settings() independently of app.state.orchestrator.

Suggested command for a future checkpoint (NOT run as part of WEB-R6, which is static-only):
    pytest tests/integration/test_web_ui_cors_and_origin.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import get_settings


def _fresh_app():
    """Import main fresh and clear the settings cache so env overrides take effect."""
    import main
    get_settings.cache_clear()
    # Other integration modules may reload config.settings during collection. Clear the
    # exact callable captured by main as well so this test remains order-independent.
    main.get_settings.cache_clear()
    app = main.create_app()
    return app


# ---------------------------------------------------------------------------
# CORS (HTTP)
# ---------------------------------------------------------------------------

def test_cors_allows_configured_origin():
    with patch.dict(os.environ, {
        "ROBOT_MODE": "mock",
        "WEB_UI_ALLOWED_ORIGINS": "http://localhost:3001",
    }, clear=False):
        app = _fresh_app()
    transport = httpx.ASGITransport(app=app)

    async def _run():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.options(
                "/status",
                headers={
                    "Origin": "http://localhost:3001",
                    "Access-Control-Request-Method": "GET",
                },
            )

    import asyncio
    resp = asyncio.run(_run())
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3001"
    get_settings.cache_clear()


def test_cors_rejects_unlisted_origin():
    with patch.dict(os.environ, {
        "ROBOT_MODE": "mock",
        "WEB_UI_ALLOWED_ORIGINS": "http://localhost:3001",
    }, clear=False):
        app = _fresh_app()
    transport = httpx.ASGITransport(app=app)

    async def _run():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.options(
                "/status",
                headers={
                    "Origin": "http://evil.example",
                    "Access-Control-Request-Method": "GET",
                },
            )

    import asyncio
    resp = asyncio.run(_run())
    assert resp.headers.get("access-control-allow-origin") is None
    get_settings.cache_clear()


def test_wildcard_origin_rejected_in_real_mode_at_validate_web_ui_config():
    with patch.dict(os.environ, {
        "ROBOT_MODE": "real",
        "ROBOT_NETWORK_INTERFACE": "eth0",
        "WEB_UI_ALLOWED_ORIGINS": "*",
    }, clear=False):
        get_settings.cache_clear()
        settings = get_settings()
        with pytest.raises(ValueError, match="wildcard_origin_prohibited_in_real_mode"):
            settings.validate_web_ui_config()
    get_settings.cache_clear()


def test_empty_origins_rejected_in_real_mode():
    with patch.dict(os.environ, {
        "ROBOT_MODE": "real",
        "ROBOT_NETWORK_INTERFACE": "eth0",
        "WEB_UI_ALLOWED_ORIGINS": "",
    }, clear=False):
        get_settings.cache_clear()
        settings = get_settings()
        with pytest.raises(ValueError, match="WEB_UI_ALLOWED_ORIGINS_empty_in_real_mode"):
            settings.validate_web_ui_config()
    get_settings.cache_clear()


def test_wildcard_origin_allowed_in_mock_mode():
    with patch.dict(os.environ, {
        "ROBOT_MODE": "mock",
        "WEB_UI_ALLOWED_ORIGINS": "*",
    }, clear=False):
        get_settings.cache_clear()
        settings = get_settings()
        settings.validate_web_ui_config()  # must not raise
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# WebSocket Origin validation (/ws/telemetry)
# ---------------------------------------------------------------------------

def test_websocket_telemetry_allowed_origin_connects():
    with patch.dict(os.environ, {
        "ROBOT_MODE": "mock",
        "WEB_UI_ALLOWED_ORIGINS": "http://localhost:3001",
    }, clear=False):
        app = _fresh_app()
    transport = httpx.ASGITransport(app=app)

    async def _run():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream(
                "GET", "/ws/telemetry",
                headers={"Origin": "http://localhost:3001"},
            ) as resp:
                return resp.status_code

    # httpx ASGITransport does not perform a real WS upgrade; instead verify the origin
    # check function directly against a fake websocket-like object exposing .headers.
    from api.router import _is_websocket_origin_allowed

    class _FakeWs:
        headers = {"origin": "http://localhost:3001"}

    assert _is_websocket_origin_allowed(_FakeWs()) is True
    get_settings.cache_clear()


def test_websocket_telemetry_rejected_origin():
    with patch.dict(os.environ, {
        "ROBOT_MODE": "mock",
        "WEB_UI_ALLOWED_ORIGINS": "http://localhost:3001",
        "WEB_UI_ALLOW_MISSING_ORIGIN": "false",
    }, clear=False):
        get_settings.cache_clear()
        from api.router import _is_websocket_origin_allowed

        class _FakeWs:
            headers = {"origin": "http://evil.example"}

        assert _is_websocket_origin_allowed(_FakeWs()) is False
    get_settings.cache_clear()


def test_websocket_telemetry_missing_origin_rejected_by_default():
    with patch.dict(os.environ, {
        "ROBOT_MODE": "mock",
        "WEB_UI_ALLOWED_ORIGINS": "http://localhost:3001",
        "WEB_UI_ALLOW_MISSING_ORIGIN": "false",
    }, clear=False):
        get_settings.cache_clear()
        from api.router import _is_websocket_origin_allowed

        class _FakeWs:
            headers = {}

        assert _is_websocket_origin_allowed(_FakeWs()) is False
    get_settings.cache_clear()


def test_websocket_telemetry_missing_origin_allowed_when_explicitly_enabled():
    with patch.dict(os.environ, {
        "ROBOT_MODE": "mock",
        "WEB_UI_ALLOWED_ORIGINS": "http://localhost:3001",
        "WEB_UI_ALLOW_MISSING_ORIGIN": "true",
    }, clear=False):
        get_settings.cache_clear()
        from api.router import _is_websocket_origin_allowed

        class _FakeWs:
            headers = {}

        assert _is_websocket_origin_allowed(_FakeWs()) is True
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# /dashboard redirect vs legacy fallback
# ---------------------------------------------------------------------------

def test_dashboard_redirects_to_web_ui_public_url_when_configured():
    with patch.dict(os.environ, {
        "ROBOT_MODE": "mock",
        "WEB_UI_PUBLIC_URL": "http://localhost:3001",
    }, clear=False):
        app = _fresh_app()
    transport = httpx.ASGITransport(app=app)

    async def _run():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/dashboard", follow_redirects=False)

    import asyncio
    resp = asyncio.run(_run())
    assert resp.status_code == 307
    assert resp.headers["location"] == "http://localhost:3001"
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Defaults de WEB_UI_ALLOWED_ORIGINS por ROBOT_MODE (cierre operativo web-ui)
# ---------------------------------------------------------------------------

def test_mock_mode_without_allowed_origins_uses_dev_defaults():
    with patch.dict(os.environ, {
        "ROBOT_MODE": "mock",
        "WEB_UI_ALLOWED_ORIGINS": "",
    }, clear=False):
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.web_ui_allowed_origins_list == [
            "http://localhost:3001",
            "http://127.0.0.1:3001",
        ]
        settings.validate_web_ui_config()  # must not raise
    get_settings.cache_clear()


def test_sim_mode_without_allowed_origins_uses_dev_defaults():
    with patch.dict(os.environ, {
        "ROBOT_MODE": "sim",
        "WEB_UI_ALLOWED_ORIGINS": "",
    }, clear=False):
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.web_ui_allowed_origins_list == [
            "http://localhost:3001",
            "http://127.0.0.1:3001",
        ]
        settings.validate_web_ui_config()  # must not raise
    get_settings.cache_clear()


def test_demo_mode_without_allowed_origins_uses_dev_defaults():
    with patch.dict(os.environ, {
        "ROBOT_MODE": "demo",
        "WEB_UI_ALLOWED_ORIGINS": "",
    }, clear=False):
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.web_ui_allowed_origins_list == [
            "http://localhost:3001",
            "http://127.0.0.1:3001",
        ]
        settings.validate_web_ui_config()  # must not raise
    get_settings.cache_clear()


def test_real_mode_without_allowed_origins_fails_closed():
    with patch.dict(os.environ, {
        "ROBOT_MODE": "real",
        "ROBOT_NETWORK_INTERFACE": "eth0",
        "WEB_UI_ALLOWED_ORIGINS": "",
    }, clear=False):
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.web_ui_allowed_origins_list == []
        with pytest.raises(ValueError, match="WEB_UI_ALLOWED_ORIGINS_empty_in_real_mode"):
            settings.validate_web_ui_config()
    get_settings.cache_clear()


def test_real_mode_with_wildcard_fails_closed():
    with patch.dict(os.environ, {
        "ROBOT_MODE": "real",
        "ROBOT_NETWORK_INTERFACE": "eth0",
        "WEB_UI_ALLOWED_ORIGINS": "*",
    }, clear=False):
        get_settings.cache_clear()
        settings = get_settings()
        with pytest.raises(ValueError, match="wildcard_origin_prohibited_in_real_mode"):
            settings.validate_web_ui_config()
    get_settings.cache_clear()


def test_real_mode_with_explicit_list_accepts_only_that_list():
    with patch.dict(os.environ, {
        "ROBOT_MODE": "real",
        "ROBOT_NETWORK_INTERFACE": "eth0",
        "WEB_UI_ALLOWED_ORIGINS": "http://192.168.123.101:3001",
    }, clear=False):
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.web_ui_allowed_origins_list == ["http://192.168.123.101:3001"]
        settings.validate_web_ui_config()  # must not raise
    get_settings.cache_clear()


def test_cors_and_websocket_share_same_effective_origins_list():
    with patch.dict(os.environ, {
        "ROBOT_MODE": "mock",
        "WEB_UI_ALLOWED_ORIGINS": "",
    }, clear=False):
        get_settings.cache_clear()
        app = _fresh_app()
        settings_for_ws = get_settings()
    transport = httpx.ASGITransport(app=app)

    async def _run():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.options(
                "/status",
                headers={
                    "Origin": "http://localhost:3001",
                    "Access-Control-Request-Method": "GET",
                },
            )

    import asyncio
    resp = asyncio.run(_run())
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3001"

    from api.router import _is_websocket_origin_allowed

    class _FakeWs:
        headers = {"origin": "http://localhost:3001"}

    assert _is_websocket_origin_allowed(_FakeWs()) is True
    assert settings_for_ws.web_ui_allowed_origins_list == [
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Evidencia documental (cierre operativo web-ui)
# ---------------------------------------------------------------------------

def _parse_active_env_assignments(content: str) -> dict[str, str]:
    """Parse only active (non-commented) KEY=VALUE lines, dotenv-style.

    A line is active if, ignoring leading whitespace, it does not start with
    "#". Inline comments after a value are not stripped (none are used in
    .env.example), so this stays a straightforward, dependency-free parser
    sufficient for this fixed-format file.
    """
    active: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        active[key.strip()] = value.strip()
    return active


def test_env_example_active_assignments_are_fail_closed_for_real_mode():
    """Copying .env.example and only flipping ROBOT_MODE=real must not inherit
    a non-empty WEB_UI_ALLOWED_ORIGINS from the example: the active assignment
    must be empty, not merely "the variable name appears somewhere in the file"."""
    env_example = PROJECT_ROOT / ".env.example"
    content = env_example.read_text(encoding="utf-8")
    active = _parse_active_env_assignments(content)

    assert "WEB_UI_ALLOWED_ORIGINS" in active
    assert active["WEB_UI_ALLOWED_ORIGINS"] == ""

    assert "WEB_UI_PUBLIC_URL" in active
    assert active["WEB_UI_PUBLIC_URL"] == ""

    assert "WEB_UI_ALLOW_MISSING_ORIGIN" in active
    assert active["WEB_UI_ALLOW_MISSING_ORIGIN"] == "false"


def test_env_example_non_empty_origin_examples_are_only_commented():
    """The non-empty example values (dev localhost, real notebook IP) must
    appear exclusively in commented-out lines, never as active assignments."""
    env_example = PROJECT_ROOT / ".env.example"
    content = env_example.read_text(encoding="utf-8")
    active = _parse_active_env_assignments(content)

    assert active["WEB_UI_ALLOWED_ORIGINS"] != "http://localhost:3001,http://127.0.0.1:3001"
    assert active["WEB_UI_PUBLIC_URL"] != "http://localhost:3001"
    assert active.get("WEB_UI_ALLOWED_ORIGINS", "").find("192.168") == -1
    assert active.get("WEB_UI_PUBLIC_URL", "").find("192.168") == -1

    commented_lines = [
        line.strip() for line in content.splitlines() if line.strip().startswith("#")
    ]
    commented_text = "\n".join(commented_lines)
    assert "WEB_UI_ALLOWED_ORIGINS=http://localhost:3001,http://127.0.0.1:3001" in commented_text
    assert "WEB_UI_PUBLIC_URL=http://localhost:3001" in commented_text
    assert "WEB_UI_ALLOWED_ORIGINS=http://192.168.123.101:3001" in commented_text
    assert "WEB_UI_PUBLIC_URL=http://192.168.123.101:3001" in commented_text


def test_runbook_contains_critical_ports_and_endpoints():
    runbook = PROJECT_ROOT.parent / "docs" / "Operaciones_HIL" / "WEB_UI_NOTEBOOK_COMPANION_RUNBOOK.md"
    content = runbook.read_text(encoding="utf-8")
    assert "3001" in content
    assert "8000" in content
    assert "/status" in content
    assert "/dashboard" in content
    assert "/ws/telemetry" in content
    assert "/emergency" in content
    assert "/tour/start" in content


def test_runbook_uses_npm_ci_not_npm_install():
    runbook = PROJECT_ROOT.parent / "docs" / "Operaciones_HIL" / "WEB_UI_NOTEBOOK_COMPANION_RUNBOOK.md"
    content = runbook.read_text(encoding="utf-8")
    assert "npm ci" in content
    assert "npm install" not in content


def test_runbook_defines_posture_preserving_stop_and_operator_authority():
    """The runbook must distinguish software stop from mechanical safety."""
    runbook = PROJECT_ROOT.parent / "docs" / "Operaciones_HIL" / "WEB_UI_NOTEBOOK_COMPANION_RUNBOOK.md"
    content = runbook.read_text(encoding="utf-8")

    assert "ORCHESTRATOR_EMERGENCY_COMPLETED" in content
    assert "StopMove" in content
    assert "operator_intervention_required=true" in content
    assert "OttoGuide nunca emite" in content

    # The warning must sit next to the literal log marker, not just exist somewhere
    # disconnected from it.
    marker_index = content.find("SECUENCIA HIL-SAFE COMPLETADA")
    assert marker_index != -1
    warning_window = content[marker_index : marker_index + 400]
    assert "NO" in warning_window
    assert "StopMove" in warning_window

    assert "de forma garantizada" not in content


def test_dashboard_returns_503_when_no_public_url_configured():
    """WEB-R6: without WEB_UI_PUBLIC_URL, "/" and "/dashboard" must NOT silently serve the
    legacy static dashboard as if it were the operational UI. They must fail explicitly
    with 503 and point the operator at WEB_UI_PUBLIC_URL."""
    with patch.dict(os.environ, {
        "ROBOT_MODE": "mock",
        "WEB_UI_PUBLIC_URL": "",
    }, clear=False):
        app = _fresh_app()
    transport = httpx.ASGITransport(app=app)

    async def _run(path):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path, follow_redirects=False)

    import asyncio
    for path in ("/", "/dashboard"):
        resp = asyncio.run(_run(path))
        assert resp.status_code == 503
        assert "WEB_UI_PUBLIC_URL" in resp.text
    get_settings.cache_clear()


def test_dashboard_legacy_endpoint_serves_static_file_marked_deprecated():
    """WEB-R6: the legacy dashboard HTML remains reachable only as an explicit, deprecated
    diagnostic endpoint at /dashboard-legacy — never as the default response of "/" or
    "/dashboard"."""
    with patch.dict(os.environ, {
        "ROBOT_MODE": "mock",
        "WEB_UI_PUBLIC_URL": "",
    }, clear=False):
        app = _fresh_app()
    transport = httpx.ASGITransport(app=app)

    async def _run():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/dashboard-legacy", follow_redirects=False)

    import asyncio
    resp = asyncio.run(_run())
    # 200 if static/dashboard.html exists in this checkout, 404 otherwise — either way,
    # a 200 must carry both the legacy marker and the deprecation header.
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        assert resp.headers.get("x-ottoguide-dashboard") == "legacy-fallback"
        assert resp.headers.get("x-ottoguide-deprecated") == "true"
    get_settings.cache_clear()
