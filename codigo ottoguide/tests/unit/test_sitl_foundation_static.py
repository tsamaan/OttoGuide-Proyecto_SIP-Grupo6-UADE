"""Static contract tests for the WSL SITL foundation.

These tests intentionally do not execute bootstraps, tmux, uvicorn, ROS, DDS,
MuJoCo, Isaac, Docker, or the FastAPI lifespan.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

REQUIREMENTS_SITL = PROJECT_ROOT / "requirements_sitl.txt"
REQUIREMENTS_PROD = PROJECT_ROOT / "requirements_prod.txt"
BOOTSTRAP_CYCLONEDDS = PROJECT_ROOT / "scripts" / "bootstrap_cyclonedds_wsl.sh"
BOOTSTRAP_SITL = PROJECT_ROOT / "scripts" / "bootstrap_sitl_wsl.sh"
LAUNCHER = PROJECT_ROOT / "scripts" / "launch_sitl_tmux.sh"
MAIN = PROJECT_ROOT / "main.py"
API_ROUTER = PROJECT_ROOT / "api" / "router.py"
LEGACY_API_SERVER = PROJECT_ROOT / "src" / "api" / "server.py"
SDK_PRIMARY = PROJECT_ROOT / "libs" / "unitree_sdk2_python"
SDK_FALLBACK = PROJECT_ROOT / "libs" / "unitree_sdk2_python-master"


CRITICAL_PINS = {
    "fastapi",
    "uvicorn",
    "pydantic",
    "pydantic_core",
    "pydantic-settings",
    "python-statemachine",
    "httpx",
    "numpy",
    "opencv-python-headless",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalized_requirement_name(raw: str) -> str:
    name = raw.split("==", 1)[0].strip()
    name = name.split("[", 1)[0]
    return name


def _pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in _read(path).splitlines():
        clean = line.split("#", 1)[0].strip()
        if not clean or clean.startswith("-"):
            continue
        if "==" not in clean:
            continue
        name, version = clean.split("==", 1)
        pins[_normalized_requirement_name(name)] = version.strip()
    return pins


def _setup_requires(setup_py: Path) -> set[str]:
    text = _read(setup_py)
    match = re.search(r"install_requires\s*=\s*\[(.*?)\]", text, re.DOTALL)
    assert match, f"install_requires missing in {setup_py}"
    return set(re.findall(r"['\"]([^'\"]+)['\"]", match.group(1)))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _active_shell_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_sitl_foundation_files_exist() -> None:
    assert REQUIREMENTS_SITL.is_file()
    assert BOOTSTRAP_CYCLONEDDS.is_file()
    assert BOOTSTRAP_SITL.is_file()
    assert LAUNCHER.is_file()


def test_bootstraps_are_wsl_x86_only_and_do_not_install_system_packages() -> None:
    for path in (BOOTSTRAP_CYCLONEDDS, BOOTSTRAP_SITL):
        text = _read(path)
        active = "\n".join(_active_shell_lines(text))
        assert "set -euo pipefail" in text
        assert "WSL_DISTRO_NAME" in text
        assert "grep -qi microsoft /proc/version" in text
        assert "x86_64" in text
        assert "aarch64|arm64" in text
        assert not re.search(r"(^|\n)\s*sudo\b", active)
        assert not re.search(r"\bapt(-get)?\s+install\b", active)
        assert "docker" not in active.lower()
        assert " -m uvicorn" not in active
        assert "uvicorn main:" not in active
        assert "ros2 launch" not in text
        assert "simulate.py" not in text
        assert "sim_main.py" not in text


def test_launcher_uses_canonical_factory_and_sitl_python() -> None:
    text = _read(LAUNCHER)
    assert "SITL_VENV_PYTHON" in text
    assert "scripts/bootstrap_sitl_wsl.sh" in text
    assert "export ROBOT_MODE=sim" in text
    assert "'${SITL_VENV_PYTHON}' -m uvicorn main:create_app --factory --host 0.0.0.0 --port 8000" in text
    assert "uvicorn main:app" not in text
    assert "--port 3000" not in text
    assert "ottoguide_web_app/backend" not in text
    assert "pilar-web" not in text


def test_sitl_pins_match_productive_manifest() -> None:
    sitl = _pins(REQUIREMENTS_SITL)
    prod = _pins(REQUIREMENTS_PROD)
    for name in CRITICAL_PINS:
        assert sitl[name] == prod[name], name


def test_cyclonedds_pin_matches_vendored_sdk_setup_py() -> None:
    sitl = _pins(REQUIREMENTS_SITL)
    assert sitl["cyclonedds"] == "0.10.2"

    setup_paths = [p / "setup.py" for p in (SDK_PRIMARY, SDK_FALLBACK) if (p / "setup.py").is_file()]
    assert setup_paths, "No vendored Unitree SDK setup.py found"
    for setup_py in setup_paths:
        assert f"cyclonedds=={sitl['cyclonedds']}" in _setup_requires(setup_py)

    if len(setup_paths) == 2:
        assert _sha256(setup_paths[0]) == _sha256(setup_paths[1])


def test_sitl_bootstrap_contains_dual_sdk_resolver_fail_closed() -> None:
    text = _read(BOOTSTRAP_SITL)
    assert "UNITREE_SDK_DIR" in text
    assert 'primary="${PROJECT_ROOT}/libs/unitree_sdk2_python"' in text
    assert 'fallback="${PROJECT_ROOT}/libs/unitree_sdk2_python-master"' in text
    assert "NO_GO_UNITREE_SDK_NOT_FOUND" in text
    assert "NO_GO_DIVERGENT_UNITREE_SDK_VENDOR_COPIES" in text
    assert "sha256sum" in text
    assert "pip install --no-deps -e" in text


def test_canonical_factory_static_contract() -> None:
    main_text = _read(MAIN)
    assert "def create_app() -> FastAPI:" in main_text
    assert "from api.router import router" in main_text
    assert "app.include_router(router)" in main_text
    assert API_ROUTER.is_file()
    assert not LEGACY_API_SERVER.exists()
    assert "src.api.server" not in main_text
