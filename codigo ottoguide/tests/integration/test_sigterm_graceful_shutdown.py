"""Subprocess regression: Uvicorn owns signals and executes lifespan once."""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_sigterm_exits_without_sigkill_and_runs_stopmove_once(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("SIGTERM subprocess contract is exercised on Linux/WSL")
    port = _free_port()
    stub_dir = tmp_path / "import_stubs"
    stub_dir.mkdir()
    (stub_dir / "pyttsx3.py").write_text(
        "def init():\n    raise RuntimeError('audio disabled in shutdown test')\n",
        encoding="utf-8",
    )
    (stub_dir / "speech_recognition.py").write_text(
        "class Recognizer: pass\nclass Microphone: pass\n",
        encoding="utf-8",
    )
    (stub_dir / "aiohttp.py").write_text(
        "class ClientError(Exception): pass\nclass ClientTimeout:\n"
        "    def __init__(self, **kwargs): pass\nclass ClientSession: pass\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "ROBOT_MODE": "mock",
            "NAVIGATION_BACKEND": "disabled",
            "NAVIGATION_ALLOW_STUB_TOURS": "false",
            "API_HOST": "127.0.0.1",
            "API_PORT": str(port),
            "WEB_UI_ALLOWED_ORIGINS": "http://127.0.0.1:3001",
            "WEB_UI_ALLOW_MISSING_ORIGIN": "true",
            "QR_STATION_TRIGGER_ENABLED": "false",
            "CLOUD_FALLBACK_ENABLED": "false",
        }
    )
    env["PYTHONPATH"] = os.pathsep.join(
        [str(stub_dir), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=creationflags,
    )
    output = ""
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            with socket.socket() as sock:
                sock.settimeout(0.1)
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.1)
        assert proc.poll() is None, "backend mock termino antes de readiness"

        if os.name == "nt":
            # Windows maps Uvicorn's graceful console signal path to SIGINT.
            proc.send_signal(signal.CTRL_C_EVENT)
        else:
            proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)
        output = proc.stdout.read() if proc.stdout else ""
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
        if proc.stdout:
            output += proc.stdout.read()

    assert proc.returncode == 0
    assert output.count("StopMove ejecutado correctamente") == 1
    assert "PROGRAMMATIC_DAMP" not in output
