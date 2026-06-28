"""
Integration tests for the web UI hardening added for pilar-web integration:
  - CORSMiddleware on main.create_app() (allowed/rejected origin, wildcard rejected in real mode)
  - Manual Origin validation on WS /ws/telemetry
  - /dashboard redirect to WEB_UI_PUBLIC_URL vs legacy static fallback

These tests call main.create_app() directly via httpx.ASGITransport WITHOUT triggering the
FastAPI lifespan (no lifespan="on"), so no hardware/orchestrator boot is exercised — only the
app-construction-time wiring (CORSMiddleware, dashboard route) and the WS handler's manual
Origin check, which reads config.settings.get_settings() independently of app.state.orchestrator.
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


def test_dashboard_serves_legacy_fallback_when_no_public_url_configured():
    with patch.dict(os.environ, {
        "ROBOT_MODE": "mock",
        "WEB_UI_PUBLIC_URL": "",
    }, clear=False):
        app = _fresh_app()
    transport = httpx.ASGITransport(app=app)

    async def _run():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/dashboard", follow_redirects=False)

    import asyncio
    resp = asyncio.run(_run())
    # 200 if static/dashboard.html exists in this checkout, 404 otherwise — either way,
    # it must NOT be a redirect, and a 200 must carry the legacy marker header.
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        assert resp.headers.get("x-ottoguide-dashboard") == "legacy-fallback"
    get_settings.cache_clear()
