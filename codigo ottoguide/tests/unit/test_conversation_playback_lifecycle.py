"""
@TASK: Verificar el ciclo de vida de tareas asyncio de reproduccion en LocalNLPPipeline y
       CloudNLPPipeline: correcto tipo pasado a create_task, registro en _playback_tasks,
       eliminacion al finalizar y cancelacion en close().
@INPUT: LocalNLPPipeline / CloudNLPPipeline con executors inyectados y funciones IO mockeadas
@OUTPUT: 11 casos de prueba (T01-T11); exit code 0 sin audio, red, Piper, Ollama ni hardware
@CONTEXT: Regresion para IA-RUNTIME-03; ejecutable en cualquier entorno Python 3.10+ con pytest.
@SECURITY: Sin I/O real; todas las llamadas a audio y HTTP estan sustituidas por mocks.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from src.interaction.conversation_manager import CloudNLPPipeline, LocalNLPPipeline

_MODULE = "src.interaction.conversation_manager"

# ---------------------------------------------------------------------------
# Helpers de construccion
# ---------------------------------------------------------------------------

def _make_local() -> LocalNLPPipeline:
    return LocalNLPPipeline(
        cpu_executor=ThreadPoolExecutor(max_workers=1),
        audio_executor=ThreadPoolExecutor(max_workers=1),
    )


def _make_cloud_http() -> AsyncMock:
    pcm_bytes = np.zeros(100, dtype=np.int16).tobytes()
    mock_response = MagicMock()
    mock_response.content = pcm_bytes
    mock_response.raise_for_status = MagicMock()
    client = AsyncMock()
    client.post = AsyncMock(return_value=mock_response)
    return client


def _make_cloud() -> CloudNLPPipeline:
    return CloudNLPPipeline(
        audio_executor=ThreadPoolExecutor(max_workers=1),
        http_client=_make_cloud_http(),
    )


# ---------------------------------------------------------------------------
# T01 — LocalNLP: synthesize_and_play no produce TypeError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t01_local_synthesize_no_type_error() -> None:
    """T01: synthesize_and_play completes without TypeError from create_task(Future)."""
    pipeline = _make_local()
    with patch(f"{_MODULE}._run_piper_synthesis", return_value=np.zeros(10, dtype=np.float32)), \
         patch(f"{_MODULE}._play_audio_alsa", return_value=None):
        await pipeline.synthesize_and_play("hola")
        await asyncio.sleep(0.05)
    pipeline.close()


# ---------------------------------------------------------------------------
# T02 — CloudNLP: _cloud_tts_openai no produce TypeError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t02_cloud_tts_no_type_error() -> None:
    """T02: _cloud_tts_openai completes without TypeError from create_task(Future)."""
    pipeline = _make_cloud()
    with patch(f"{_MODULE}._play_audio_alsa", return_value=None):
        await pipeline._cloud_tts_openai("hola")
        await asyncio.sleep(0.05)
    pipeline.close()


# ---------------------------------------------------------------------------
# T03 — Tarea local registrada inmediatamente despues de programarse
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t03_local_task_registered() -> None:
    """T03: Task is in _playback_tasks before ALSA playback completes."""
    release = threading.Event()

    def blocking_alsa(*args: object) -> None:
        release.wait(timeout=5.0)

    pipeline = _make_local()
    with patch(f"{_MODULE}._run_piper_synthesis", return_value=np.zeros(10, dtype=np.float32)), \
         patch(f"{_MODULE}._play_audio_alsa", side_effect=blocking_alsa):
        await pipeline.synthesize_and_play("test")
        assert len(pipeline._playback_tasks) >= 1, "Task must be registered before completion"
        release.set()
        await asyncio.sleep(0.05)
    pipeline.close()


# ---------------------------------------------------------------------------
# T04 — Tarea local eliminada del registro al finalizar
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t04_local_task_removed_after_completion() -> None:
    """T04: Task is removed from _playback_tasks once it finishes."""
    pipeline = _make_local()
    with patch(f"{_MODULE}._run_piper_synthesis", return_value=np.zeros(10, dtype=np.float32)), \
         patch(f"{_MODULE}._play_audio_alsa", return_value=None):
        await pipeline.synthesize_and_play("test")
        await asyncio.sleep(0.2)
        assert len(pipeline._playback_tasks) == 0, "Task must be removed after done callback"
    pipeline.close()


# ---------------------------------------------------------------------------
# T05 — Tarea cloud registrada y luego eliminada
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t05_cloud_task_registered_and_removed() -> None:
    """T05: Cloud playback task appears in _playback_tasks then is removed."""
    release = threading.Event()

    def blocking_alsa(*args: object) -> None:
        release.wait(timeout=5.0)

    pipeline = _make_cloud()
    with patch(f"{_MODULE}._play_audio_alsa", side_effect=blocking_alsa):
        await pipeline._cloud_tts_openai("test")
        assert len(pipeline._playback_tasks) >= 1, "Cloud task must be registered"
        release.set()
        await asyncio.sleep(0.2)
        assert len(pipeline._playback_tasks) == 0, "Cloud task must be removed after completion"
    pipeline.close()


# ---------------------------------------------------------------------------
# T06 — Excepcion en _play_audio_alsa es observada y registrada
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t06_alsa_exception_logged(caplog: pytest.LogCaptureFixture) -> None:
    """T06: An exception from _play_audio_alsa is logged, not propagated."""
    def failing_alsa(*args: object) -> None:
        raise RuntimeError("ALSA device unavailable")

    pipeline = _make_local()
    with patch(f"{_MODULE}._run_piper_synthesis", return_value=np.zeros(10, dtype=np.float32)), \
         patch(f"{_MODULE}._play_audio_alsa", side_effect=failing_alsa), \
         caplog.at_level(logging.WARNING, logger=_MODULE):
        await pipeline.synthesize_and_play("test")
        await asyncio.sleep(0.2)

    assert len(pipeline._playback_tasks) == 0
    assert any(
        "Excepcion" in r.getMessage() or "ALSA" in r.getMessage()
        for r in caplog.records
    ), f"Expected exception log; got: {[r.getMessage() for r in caplog.records]}"
    pipeline.close()


# ---------------------------------------------------------------------------
# T07 — Tarea cancelada no genera log de error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t07_cancelled_task_no_error_log(caplog: pytest.LogCaptureFixture) -> None:
    """T07: A cancelled playback task does not produce an error log entry."""
    release = threading.Event()

    def blocking_alsa(*args: object) -> None:
        release.wait(timeout=5.0)

    pipeline = _make_local()
    with patch(f"{_MODULE}._run_piper_synthesis", return_value=np.zeros(10, dtype=np.float32)), \
         patch(f"{_MODULE}._play_audio_alsa", side_effect=blocking_alsa), \
         caplog.at_level(logging.WARNING, logger=_MODULE):
        await pipeline.synthesize_and_play("test")
        for task in list(pipeline._playback_tasks):
            task.cancel()
        await asyncio.sleep(0.05)

    excepcion_records = [r for r in caplog.records if "Excepcion" in r.getMessage()]
    assert len(excepcion_records) == 0, (
        f"Cancelled task must not log exception; got: {[r.getMessage() for r in excepcion_records]}"
    )
    release.set()
    pipeline.close()


# ---------------------------------------------------------------------------
# T08 — close() cancela tareas pendientes locales
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t08_local_close_cancels_pending() -> None:
    """T08: close() cancels all pending playback tasks in LocalNLPPipeline."""
    release = threading.Event()

    def blocking_alsa(*args: object) -> None:
        release.wait(timeout=5.0)

    pipeline = _make_local()
    with patch(f"{_MODULE}._run_piper_synthesis", return_value=np.zeros(10, dtype=np.float32)), \
         patch(f"{_MODULE}._play_audio_alsa", side_effect=blocking_alsa):
        await pipeline.synthesize_and_play("test")
        assert len(pipeline._playback_tasks) >= 1
        pipeline.close()
        assert len(pipeline._playback_tasks) == 0, "_playback_tasks must be cleared by close()"
    release.set()


# ---------------------------------------------------------------------------
# T09 — close() cancela tareas pendientes cloud
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t09_cloud_close_cancels_pending() -> None:
    """T09: close() cancels all pending playback tasks in CloudNLPPipeline."""
    release = threading.Event()

    def blocking_alsa(*args: object) -> None:
        release.wait(timeout=5.0)

    pipeline = _make_cloud()
    with patch(f"{_MODULE}._play_audio_alsa", side_effect=blocking_alsa):
        await pipeline._cloud_tts_openai("test")
        assert len(pipeline._playback_tasks) >= 1
        pipeline.close()
        assert len(pipeline._playback_tasks) == 0, "_playback_tasks must be cleared by close()"
    release.set()


# ---------------------------------------------------------------------------
# T10 — Ningun test accede a audio, red, Piper, Ollama ni hardware
# ---------------------------------------------------------------------------

def test_t10_no_real_io_accessed() -> None:
    """T10: Prohibited hardware/network modules are not loaded in test scope."""
    import sys
    prohibited = {"sounddevice", "piper", "faster_whisper", "ollama"}
    loaded_prohibited = {name for name in prohibited if name in sys.modules}
    assert not loaded_prohibited, (
        f"Prohibited modules must not be loaded: {loaded_prohibited}"
    )


# ---------------------------------------------------------------------------
# T11 — Probe de regresion: Future directo a create_task sigue produciendo TypeError
# ---------------------------------------------------------------------------

def test_t11_regression_probe_create_task_rejects_future() -> None:
    """T11: Python 3.10.11 C asyncio raises TypeError when create_task receives a Future."""
    async def run_probe() -> None:
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = loop.run_in_executor(executor, lambda: None)
            with pytest.raises(TypeError, match="coroutine"):
                asyncio.create_task(future)  # type: ignore[arg-type]
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    asyncio.run(run_probe())
