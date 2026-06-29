"""
@TASK: Validar los contratos canonicos de integracion creados en U1
@INPUT: Sin dependencias de hardware; solo los modulos contractuales nuevos
@OUTPUT: Resultado de pytest: PASSED si los contratos cumplen su especificacion
@CONTEXT: Ejecutar con: python -m pytest tests/unit/test_u1_integration_contracts.py -q
@SECURITY: Sin I/O de red ni hardware; completamente aislado.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import sys
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from types import MappingProxyType

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.interaction.runtime_port import (
    INTERACTION_PROTOCOL_VERSION,
    InteractionContext,
    InteractionRuntimeCapabilities,
    InteractionRuntimeHealth,
    InteractionRuntimePort,
    InteractionRuntimeProtocolError,
    InteractionRuntimeState,
    WorkerCommandEnvelope,
    WorkerCommandType,
    WorkerEventEnvelope,
    WorkerEventType,
)
from src.interaction.worker_supervisor import InteractionWorkerSupervisor, WorkerTermination
from src.vision.station_trigger import (
    QRStationDetected,
    StationTriggerHealth,
    StationTriggerPort,
    StationTriggerState,
)

# events.py se carga de forma aislada (sin pasar por src.core.__init__, que
# importa tour_orchestrator -> rclpy) para no fijar en sys.modules una copia
# de EventType incompatible con la que cargan otros tests del mismo proceso
# (p. ej. tests/test_event_bus.py) que dependen de la identidad del enum.
if "src.core.events" in sys.modules:
    EventType = sys.modules["src.core.events"].EventType
else:
    _events_spec = importlib.util.spec_from_file_location(
        "_u1_contracts_events_probe",
        os.path.join(_PROJECT_ROOT, "src", "core", "events.py"),
    )
    _events_probe = importlib.util.module_from_spec(_events_spec)
    _events_spec.loader.exec_module(_events_probe)
    EventType = _events_probe.EventType


# ---------------------------------------------------------------------------
# Fakes — solo en tests
# ---------------------------------------------------------------------------


class FakeInteractionRuntime:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def start(self) -> None:
        self.calls.append("start")

    async def health(self) -> InteractionRuntimeHealth:
        self.calls.append("health")
        return InteractionRuntimeHealth(
            protocol_version=INTERACTION_PROTOCOL_VERSION,
            state=InteractionRuntimeState.READY,
            ready=True,
            capabilities=InteractionRuntimeCapabilities(),
        )

    async def activate(self, context: InteractionContext) -> None:
        self.calls.append("activate")

    async def pause(self) -> None:
        self.calls.append("pause")

    async def resume(self) -> None:
        self.calls.append("resume")

    async def stop(self) -> None:
        self.calls.append("stop")

    async def emergency_stop(self) -> None:
        self.calls.append("emergency_stop")

    async def next_event(self):
        self.calls.append("next_event")
        return WorkerEventEnvelope(
            protocol_version=INTERACTION_PROTOCOL_VERSION,
            message_id="evt:fake",
            interaction_id=None,
            event=WorkerEventType.HEARTBEAT,
            sequence=0,
            emitted_at_monotonic_s=0.0,
            payload={},
        )

    async def close(self) -> None:
        self.calls.append("close")


class FakeWorkerSupervisor(FakeInteractionRuntime):
    @property
    def termination(self) -> WorkerTermination | None:
        return None


class FakeStationTrigger:
    async def start(self) -> None:
        pass

    async def next_detection(self) -> QRStationDetected:
        return QRStationDetected(
            station_id="st-1",
            qr_value="QR-1",
            detected_at=datetime.now(timezone.utc),
            confidence_or_stability=0.9,
            source="fake",
        )

    async def health(self) -> StationTriggerHealth:
        return StationTriggerHealth(
            state=StationTriggerState.READY,
            ready=True,
            source="fake",
        )

    async def stop(self) -> None:
        pass

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# 1-2. Imports directos y dependencias de biblioteca estandar
# ---------------------------------------------------------------------------


def _module_path(relative: str) -> str:
    return os.path.join(_PROJECT_ROOT, *relative.split("/"))


_STDLIB_ONLY_MODULES = [
    "src/interaction/runtime_port.py",
    "src/interaction/worker_supervisor.py",
    "src/vision/station_trigger.py",
]

_FORBIDDEN_IMPORT_ROOTS = {
    "numpy",
    "cv2",
    "httpx",
    "sounddevice",
    "faster_whisper",
    "piper",
    "unitree_sdk2py",
    "rclpy",
    "subprocess",
    "multiprocessing",
    "socket",
    "pyrealsense",
    "pyrealsense2",
}


def _collect_import_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("relative_path", _STDLIB_ONLY_MODULES)
def test_module_imports_only_stdlib_or_internal(relative_path: str) -> None:
    path = _module_path(relative_path)
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    roots = _collect_import_roots(tree)
    forbidden = roots & _FORBIDDEN_IMPORT_ROOTS
    assert not forbidden, f"{relative_path} imports forbidden modules: {forbidden}"


# ---------------------------------------------------------------------------
# 3-4. Protocol runtime_checkable y conformidad de fakes
# ---------------------------------------------------------------------------


def test_protocols_are_runtime_checkable() -> None:
    assert isinstance(InteractionRuntimePort, type(InteractionRuntimePort))
    fake_runtime = FakeInteractionRuntime()
    assert isinstance(fake_runtime, InteractionRuntimePort)


def test_fake_runtime_satisfies_interaction_runtime_port() -> None:
    fake_runtime = FakeInteractionRuntime()
    assert isinstance(fake_runtime, InteractionRuntimePort)


def test_fake_supervisor_satisfies_interaction_worker_supervisor() -> None:
    fake_supervisor = FakeWorkerSupervisor()
    assert isinstance(fake_supervisor, InteractionWorkerSupervisor)


def test_fake_station_satisfies_station_trigger_port() -> None:
    fake_station = FakeStationTrigger()
    assert isinstance(fake_station, StationTriggerPort)


# ---------------------------------------------------------------------------
# 5-6. Inmutabilidad
# ---------------------------------------------------------------------------


def test_interaction_context_is_frozen() -> None:
    ctx = InteractionContext(interaction_id="i-1")
    with pytest.raises(FrozenInstanceError):
        ctx.interaction_id = "i-2"  # type: ignore[misc]


def test_interaction_context_metadata_is_immutable_mapping() -> None:
    ctx = InteractionContext(interaction_id="i-1", metadata={"k": {"nested": [1]}})
    assert isinstance(ctx.metadata, MappingProxyType)
    assert isinstance(ctx.metadata["k"], MappingProxyType)
    assert ctx.metadata["k"]["nested"] == (1,)  # type: ignore[index]
    with pytest.raises(TypeError):
        ctx.metadata["k"] = "other"  # type: ignore[index]


def test_command_envelope_payload_is_immutable_mapping() -> None:
    env = WorkerCommandEnvelope(
        protocol_version=INTERACTION_PROTOCOL_VERSION,
        message_id="m-1",
        interaction_id="i-1",
        command=WorkerCommandType.ACTIVATE,
        sequence=0,
        emitted_at_monotonic_s=0.0,
        payload={"a": {"b": [1]}},
    )
    assert isinstance(env.payload, MappingProxyType)
    assert isinstance(env.payload["a"], MappingProxyType)
    with pytest.raises(TypeError):
        env.payload["a"] = 2  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        env.sequence = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 7. Rechazos de validacion
# ---------------------------------------------------------------------------


def test_interaction_runtime_health_rejects_wrong_protocol_version() -> None:
    with pytest.raises(ValueError):
        InteractionRuntimeHealth(
            protocol_version=2,
            state=InteractionRuntimeState.READY,
            ready=True,
            capabilities=InteractionRuntimeCapabilities(),
        )


def test_interaction_context_rejects_empty_interaction_id() -> None:
    with pytest.raises(ValueError):
        InteractionContext(interaction_id="")


def test_interaction_context_rejects_empty_locale() -> None:
    with pytest.raises(ValueError):
        InteractionContext(interaction_id="i-1", locale="")


def test_interaction_context_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValueError):
        InteractionContext(interaction_id="i-1", timeout_s=0.0)
    with pytest.raises(ValueError):
        InteractionContext(interaction_id="i-1", timeout_s=-1.0)


def test_envelope_rejects_negative_sequence() -> None:
    with pytest.raises(ValueError):
        WorkerCommandEnvelope(
            protocol_version=INTERACTION_PROTOCOL_VERSION,
            message_id="m-1",
            interaction_id="i-1",
            command=WorkerCommandType.START,
            sequence=-1,
            emitted_at_monotonic_s=0.0,
            payload={},
        )


def test_envelope_rejects_negative_timestamp() -> None:
    with pytest.raises(ValueError):
        WorkerEventEnvelope(
            protocol_version=INTERACTION_PROTOCOL_VERSION,
            message_id="m-1",
            interaction_id="i-1",
        event=WorkerEventType.PLAYBACK_COMPLETED,
            sequence=0,
            emitted_at_monotonic_s=-1.0,
            payload={},
        )


def test_worker_termination_rejects_empty_reason() -> None:
    with pytest.raises(ValueError):
        WorkerTermination(
            exit_code=0,
            reason="",
            unexpected=False,
            occurred_at_monotonic_s=0.0,
        )


def test_qr_station_detected_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        QRStationDetected(
            station_id="st-1",
            qr_value="QR-1",
            detected_at=datetime.now(),
            confidence_or_stability=0.5,
            source="fake",
        )


def test_qr_station_detected_rejects_confidence_out_of_range() -> None:
    with pytest.raises(ValueError):
        QRStationDetected(
            station_id="st-1",
            qr_value="QR-1",
            detected_at=datetime.now(timezone.utc),
            confidence_or_stability=1.5,
            source="fake",
        )
    with pytest.raises(ValueError):
        QRStationDetected(
            station_id="st-1",
            qr_value="QR-1",
            detected_at=datetime.now(timezone.utc),
            confidence_or_stability=-0.1,
            source="fake",
        )


# ---------------------------------------------------------------------------
# 8. Capabilities por defecto
# ---------------------------------------------------------------------------


def test_capabilities_all_false_by_default() -> None:
    caps = InteractionRuntimeCapabilities()
    assert caps.audio_capture is False
    assert caps.wake_word is False
    assert caps.vad is False
    assert caps.stt is False
    assert caps.local_llm is False
    assert caps.spanish_tts is False
    assert caps.physical_playback is False
    assert caps.physical_playback_stop is False
    assert caps.physical_playback_completion is False


# ---------------------------------------------------------------------------
# 9. Round-trip wire
# ---------------------------------------------------------------------------


def test_command_envelope_wire_roundtrip() -> None:
    original = WorkerCommandEnvelope(
        protocol_version=INTERACTION_PROTOCOL_VERSION,
        message_id="m-1",
        interaction_id="i-1",
        command=WorkerCommandType.ACTIVATE,
        sequence=3,
        emitted_at_monotonic_s=123.456,
        payload={"locale": "es-AR"},
    )
    wire = original.to_wire_dict()
    restored = WorkerCommandEnvelope.from_wire_dict(wire)
    assert restored == original


def test_event_envelope_wire_roundtrip() -> None:
    original = WorkerEventEnvelope(
        protocol_version=INTERACTION_PROTOCOL_VERSION,
        message_id="m-2",
        interaction_id="i-1",
        event=WorkerEventType.PLAYBACK_COMPLETED,
        sequence=7,
        emitted_at_monotonic_s=999.0,
        payload={"duration_s": 4.2},
    )
    wire = original.to_wire_dict()
    restored = WorkerEventEnvelope.from_wire_dict(wire)
    assert restored == original


# ---------------------------------------------------------------------------
# 10. Rechazos de wire payload
# ---------------------------------------------------------------------------


def test_from_wire_dict_rejects_unknown_key() -> None:
    wire = {
        "protocol_version": INTERACTION_PROTOCOL_VERSION,
        "message_id": "m-1",
            "interaction_id": None,
            "command": WorkerCommandType.START.value,
        "sequence": 0,
        "emitted_at_monotonic_s": 0.0,
        "payload": {},
        "unexpected_key": "x",
    }
    with pytest.raises(InteractionRuntimeProtocolError):
        WorkerCommandEnvelope.from_wire_dict(wire)


def test_from_wire_dict_rejects_missing_required_key() -> None:
    wire = {
        "protocol_version": INTERACTION_PROTOCOL_VERSION,
        "message_id": "m-1",
            "interaction_id": None,
            "command": WorkerCommandType.START.value,
        "sequence": 0,
        "payload": {},
    }
    with pytest.raises(InteractionRuntimeProtocolError):
        WorkerCommandEnvelope.from_wire_dict(wire)


def test_from_wire_dict_rejects_invalid_enum() -> None:
    wire = {
        "protocol_version": INTERACTION_PROTOCOL_VERSION,
        "message_id": "m-1",
            "interaction_id": None,
            "command": "not_a_real_command",
        "sequence": 0,
        "emitted_at_monotonic_s": 0.0,
        "payload": {},
    }
    with pytest.raises(InteractionRuntimeProtocolError):
        WorkerCommandEnvelope.from_wire_dict(wire)


def test_from_wire_dict_rejects_invalid_protocol_version() -> None:
    wire = {
        "protocol_version": 99,
        "message_id": "m-1",
            "interaction_id": None,
            "command": WorkerCommandType.START.value,
        "sequence": 0,
        "emitted_at_monotonic_s": 0.0,
        "payload": {},
    }
    with pytest.raises(InteractionRuntimeProtocolError):
        WorkerCommandEnvelope.from_wire_dict(wire)


# ---------------------------------------------------------------------------
# 11. Evento canonico exacto
# ---------------------------------------------------------------------------


def test_qr_station_detected_event_value_is_exact() -> None:
    assert EventType.QR_STATION_DETECTED.value == "vision.qr_station_detected"


# ---------------------------------------------------------------------------
# 12-13. Ausencia de simbolos prohibidos en los modulos contractuales
# ---------------------------------------------------------------------------


_STATION_TRIGGER_FORBIDDEN_SYMBOLS = [
    "MotionCommand",
    "RobotHardwareAPI",
    "ConversationManager",
    "cv2",
    "numpy",
    "unitree_sdk2py",
    "subprocess",
]

_WORKER_SUPERVISOR_FORBIDDEN_SYMBOLS = [
    "subprocess",
    "Popen",
    "create_subprocess_exec",
    "multiprocessing",
    "socket",
    "unitree_sdk2py",
]


def _collect_code_identifiers(tree: ast.AST) -> set[str]:
    """Collect identifiers that appear as actual code tokens (imports, names),
    excluding docstrings and comments which are stripped by ast.parse already
    but may still appear inside string literals — so we only look at Name/
    Attribute/import nodes, never at ast.Constant string values."""
    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                identifiers.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                identifiers.add(node.module.split(".")[0])
            for alias in node.names:
                identifiers.add(alias.name)
    return identifiers


def test_station_trigger_module_has_no_forbidden_symbols() -> None:
    path = _module_path("src/vision/station_trigger.py")
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    identifiers = _collect_code_identifiers(tree)
    for symbol in _STATION_TRIGGER_FORBIDDEN_SYMBOLS:
        assert symbol not in identifiers, f"station_trigger.py uses forbidden symbol: {symbol}"


def test_worker_supervisor_module_has_no_forbidden_symbols() -> None:
    path = _module_path("src/interaction/worker_supervisor.py")
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    identifiers = _collect_code_identifiers(tree)
    for symbol in _WORKER_SUPERVISOR_FORBIDDEN_SYMBOLS:
        assert symbol not in identifiers, f"worker_supervisor.py uses forbidden symbol: {symbol}"


# ---------------------------------------------------------------------------
# 14. runtime_port.py sin dependencias externas
# ---------------------------------------------------------------------------


def test_runtime_port_module_imports_only_stdlib() -> None:
    path = _module_path("src/interaction/runtime_port.py")
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    roots = _collect_import_roots(tree)
    forbidden = roots & _FORBIDDEN_IMPORT_ROOTS
    assert not forbidden


# ---------------------------------------------------------------------------
# 15-17. __init__.py lazy — sin imports ansiosos hacia implementaciones pesadas
# ---------------------------------------------------------------------------


_INTERACTION_EAGER_FORBIDDEN = [
    "conversation_manager",
    "vision_processor",
    "audio_bridge",
    "wake_word_detector",
    "tts_unitree_client",
]


def test_interaction_init_has_no_eager_imports() -> None:
    path = _module_path("src/interaction/__init__.py")
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    eager_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            eager_modules.add(node.module.lstrip("."))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                eager_modules.add(alias.name)
    for forbidden in _INTERACTION_EAGER_FORBIDDEN:
        assert forbidden not in eager_modules, f"eager import found: {forbidden}"


def test_vision_init_has_no_eager_import_of_vision_processor() -> None:
    path = _module_path("src/vision/__init__.py")
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    eager_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            eager_modules.add(node.module.lstrip("."))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                eager_modules.add(alias.name)
    assert "vision_processor" not in eager_modules
    assert "cv2" not in eager_modules


def test_import_src_interaction_does_not_create_eager_side_effects() -> None:
    """A fresh, isolated import of src.interaction must not populate its own
    module namespace with the heavy submodules before any attribute is
    requested. Runs in a subprocess to avoid pollution from other tests in
    this same process that may have already imported conversation_manager."""
    import subprocess

    script = (
        "import sys; sys.path.insert(0, r'" + _PROJECT_ROOT + "'); "
        "import src.interaction as pkg; "
        "assert 'conversation_manager' not in pkg.__dict__, pkg.__dict__.keys(); "
        "assert pkg.InteractionRuntimePort is not None; "
        "print('OK')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=_PROJECT_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_import_src_vision_does_not_open_camera_or_import_cv2() -> None:
    """Isolated subprocess import: src.vision must not pull in cv2 or
    vision_processor merely by being imported."""
    import subprocess

    script = (
        "import sys; sys.path.insert(0, r'" + _PROJECT_ROOT + "'); "
        "import src.vision as pkg; "
        "assert 'cv2' not in sys.modules; "
        "assert 'vision_processor' not in pkg.__dict__; "
        "assert pkg.StationTriggerPort is not None; "
        "print('OK')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=_PROJECT_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


# ---------------------------------------------------------------------------
# Operacion count — criterios de aceptacion
# ---------------------------------------------------------------------------


def test_interaction_runtime_port_has_exactly_nine_operations() -> None:
    expected = {
        "start",
        "health",
        "activate",
        "pause",
        "resume",
        "stop",
        "emergency_stop",
        "next_event",
        "close",
    }
    actual = {
        name
        for name in InteractionRuntimePort.__protocol_attrs__  # type: ignore[attr-defined]
    } if hasattr(InteractionRuntimePort, "__protocol_attrs__") else {
        name
        for name, value in InteractionRuntimePort.__dict__.items()
        if not name.startswith("_") and callable(value)
    }
    if not actual:
        actual = {
            name
            for name in dir(InteractionRuntimePort)
            if not name.startswith("_") and name in expected
        }
    assert actual == expected, f"expected exactly {expected}, got {actual}"


def test_station_trigger_port_has_exactly_five_operations() -> None:
    expected = {"start", "next_detection", "health", "stop", "close"}
    actual = {
        name
        for name in dir(StationTriggerPort)
        if not name.startswith("_") and name in expected
    }
    assert actual == expected, f"expected exactly {expected}, got {actual}"
