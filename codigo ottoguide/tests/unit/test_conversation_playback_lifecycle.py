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
# Helpers de construccion e infraestructura de mocks
# ---------------------------------------------------------------------------

def _make_cloud_http() -> AsyncMock:
    """Crea un cliente HTTP completamente mockeado que devuelve PCM int16 valido."""
    pcm_bytes = np.zeros(100, dtype=np.int16).tobytes()
    mock_response = MagicMock()
    mock_response.content = pcm_bytes
    mock_response.raise_for_status = MagicMock()
    client = AsyncMock()
    client.post = AsyncMock(return_value=mock_response)
    return client


# ---------------------------------------------------------------------------
# T01 — LocalNLP: synthesize_and_play no produce TypeError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t01_local_synthesize_no_type_error() -> None:
    """T01: synthesize_and_play completes without TypeError from create_task(Future)."""
    cpu_exec = ThreadPoolExecutor(max_workers=1)
    audio_exec = ThreadPoolExecutor(max_workers=1)
    pipeline = LocalNLPPipeline(cpu_executor=cpu_exec, audio_executor=audio_exec)
    try:
        with patch(f"{_MODULE}._run_piper_synthesis", return_value=np.zeros(10, dtype=np.float32)), \
             patch(f"{_MODULE}._play_audio_alsa", return_value=None):
            await pipeline.synthesize_and_play("hola")
            await asyncio.sleep(0.05)
    finally:
        pipeline.close()
        cpu_exec.shutdown(wait=True, cancel_futures=True)
        audio_exec.shutdown(wait=True, cancel_futures=True)


# ---------------------------------------------------------------------------
# T02 — CloudNLP: _cloud_tts_openai no produce TypeError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t02_cloud_tts_no_type_error() -> None:
    """T02: _cloud_tts_openai completes without TypeError from create_task(Future)."""
    audio_exec = ThreadPoolExecutor(max_workers=1)
    pipeline = CloudNLPPipeline(audio_executor=audio_exec, http_client=_make_cloud_http())
    try:
        with patch(f"{_MODULE}._play_audio_alsa", return_value=None):
            await pipeline._cloud_tts_openai("hola")
            await asyncio.sleep(0.05)
    finally:
        pipeline.close()
        audio_exec.shutdown(wait=True, cancel_futures=True)


# ---------------------------------------------------------------------------
# T03 — Tarea local registrada inmediatamente despues de programarse
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t03_local_task_registered() -> None:
    """T03: Task is in _playback_tasks before ALSA playback completes."""
    release = threading.Event()

    def blocking_alsa(*args: object) -> None:
        release.wait(timeout=5.0)

    cpu_exec = ThreadPoolExecutor(max_workers=1)
    audio_exec = ThreadPoolExecutor(max_workers=1)
    pipeline = LocalNLPPipeline(cpu_executor=cpu_exec, audio_executor=audio_exec)
    try:
        with patch(f"{_MODULE}._run_piper_synthesis", return_value=np.zeros(10, dtype=np.float32)), \
             patch(f"{_MODULE}._play_audio_alsa", side_effect=blocking_alsa):
            await pipeline.synthesize_and_play("test")
            assert len(pipeline._playback_tasks) >= 1, "Task must be registered before completion"
            release.set()
            await asyncio.sleep(0.05)
    finally:
        release.set()  # idempotente; garantiza que el worker no quede bloqueado
        pipeline.close()
        cpu_exec.shutdown(wait=True, cancel_futures=True)
        audio_exec.shutdown(wait=True, cancel_futures=True)


# ---------------------------------------------------------------------------
# T04 — Tarea local eliminada del registro al finalizar
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t04_local_task_removed_after_completion() -> None:
    """T04: Task is removed from _playback_tasks once it finishes."""
    cpu_exec = ThreadPoolExecutor(max_workers=1)
    audio_exec = ThreadPoolExecutor(max_workers=1)
    pipeline = LocalNLPPipeline(cpu_executor=cpu_exec, audio_executor=audio_exec)
    try:
        with patch(f"{_MODULE}._run_piper_synthesis", return_value=np.zeros(10, dtype=np.float32)), \
             patch(f"{_MODULE}._play_audio_alsa", return_value=None):
            await pipeline.synthesize_and_play("test")
            await asyncio.sleep(0.2)
            assert len(pipeline._playback_tasks) == 0, "Task must be removed after done callback"
    finally:
        pipeline.close()
        cpu_exec.shutdown(wait=True, cancel_futures=True)
        audio_exec.shutdown(wait=True, cancel_futures=True)


# ---------------------------------------------------------------------------
# T05 — Tarea cloud registrada y luego eliminada
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t05_cloud_task_registered_and_removed() -> None:
    """T05: Cloud playback task appears in _playback_tasks then is removed."""
    release = threading.Event()

    def blocking_alsa(*args: object) -> None:
        release.wait(timeout=5.0)

    audio_exec = ThreadPoolExecutor(max_workers=1)
    pipeline = CloudNLPPipeline(audio_executor=audio_exec, http_client=_make_cloud_http())
    try:
        with patch(f"{_MODULE}._play_audio_alsa", side_effect=blocking_alsa):
            await pipeline._cloud_tts_openai("test")
            assert len(pipeline._playback_tasks) >= 1, "Cloud task must be registered"
            release.set()
            await asyncio.sleep(0.2)
            assert len(pipeline._playback_tasks) == 0, "Cloud task must be removed after completion"
    finally:
        release.set()
        pipeline.close()
        audio_exec.shutdown(wait=True, cancel_futures=True)


# ---------------------------------------------------------------------------
# T06 — Excepcion en _play_audio_alsa es observada y registrada
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t06_alsa_exception_logged(caplog: pytest.LogCaptureFixture) -> None:
    """T06: An exception from _play_audio_alsa is logged, not propagated."""
    def failing_alsa(*args: object) -> None:
        raise RuntimeError("ALSA device unavailable")

    cpu_exec = ThreadPoolExecutor(max_workers=1)
    audio_exec = ThreadPoolExecutor(max_workers=1)
    pipeline = LocalNLPPipeline(cpu_executor=cpu_exec, audio_executor=audio_exec)
    try:
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
    finally:
        pipeline.close()
        cpu_exec.shutdown(wait=True, cancel_futures=True)
        audio_exec.shutdown(wait=True, cancel_futures=True)


# ---------------------------------------------------------------------------
# T07 — Tarea cancelada no genera log de error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t07_cancelled_task_no_error_log(caplog: pytest.LogCaptureFixture) -> None:
    """T07: A cancelled playback task does not produce an error log entry."""
    release = threading.Event()

    def blocking_alsa(*args: object) -> None:
        release.wait(timeout=5.0)

    cpu_exec = ThreadPoolExecutor(max_workers=1)
    audio_exec = ThreadPoolExecutor(max_workers=1)
    pipeline = LocalNLPPipeline(cpu_executor=cpu_exec, audio_executor=audio_exec)
    try:
        with patch(f"{_MODULE}._run_piper_synthesis", return_value=np.zeros(10, dtype=np.float32)), \
             patch(f"{_MODULE}._play_audio_alsa", side_effect=blocking_alsa), \
             caplog.at_level(logging.WARNING, logger=_MODULE):
            await pipeline.synthesize_and_play("test")
            for task in list(pipeline._playback_tasks):
                task.cancel()
            await asyncio.sleep(0.05)

        excepcion_records = [r for r in caplog.records if "Excepcion" in r.getMessage()]
        assert len(excepcion_records) == 0, (
            f"Cancelled task must not log exception; got: "
            f"{[r.getMessage() for r in excepcion_records]}"
        )
    finally:
        release.set()  # desbloquear el worker antes del shutdown
        pipeline.close()
        cpu_exec.shutdown(wait=True, cancel_futures=True)
        audio_exec.shutdown(wait=True, cancel_futures=True)


# ---------------------------------------------------------------------------
# T08 — close() cancela tareas pendientes locales y las deja en estado terminal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t08_local_close_cancels_pending() -> None:
    """T08: close() cancels pending local tasks; tasks reach cancelled/done state."""
    release = threading.Event()

    def blocking_alsa(*args: object) -> None:
        release.wait(timeout=5.0)

    cpu_exec = ThreadPoolExecutor(max_workers=1)
    audio_exec = ThreadPoolExecutor(max_workers=1)
    pipeline = LocalNLPPipeline(cpu_executor=cpu_exec, audio_executor=audio_exec)
    try:
        with patch(f"{_MODULE}._run_piper_synthesis", return_value=np.zeros(10, dtype=np.float32)), \
             patch(f"{_MODULE}._play_audio_alsa", side_effect=blocking_alsa):
            await pipeline.synthesize_and_play("test")

            pending_tasks = list(pipeline._playback_tasks)
            assert pending_tasks, "There must be at least one pending task before close()"
            task = pending_tasks[0]

            pipeline.close()
            await asyncio.sleep(0)  # permite que el event loop procese la cancelacion

            assert task.cancelled() or task.done(), (
                "Task must be in cancelled or done state after close()"
            )
            assert task not in pipeline._playback_tasks, (
                "Task must be removed from _playback_tasks by close()"
            )
    finally:
        release.set()
        cpu_exec.shutdown(wait=True, cancel_futures=True)
        audio_exec.shutdown(wait=True, cancel_futures=True)


# ---------------------------------------------------------------------------
# T09 — close() cancela tareas pendientes cloud y las deja en estado terminal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t09_cloud_close_cancels_pending() -> None:
    """T09: close() cancels pending cloud tasks; tasks reach cancelled/done state."""
    release = threading.Event()

    def blocking_alsa(*args: object) -> None:
        release.wait(timeout=5.0)

    audio_exec = ThreadPoolExecutor(max_workers=1)
    pipeline = CloudNLPPipeline(audio_executor=audio_exec, http_client=_make_cloud_http())
    try:
        with patch(f"{_MODULE}._play_audio_alsa", side_effect=blocking_alsa):
            await pipeline._cloud_tts_openai("test")

            pending_tasks = list(pipeline._playback_tasks)
            assert pending_tasks, "There must be at least one pending task before close()"
            task = pending_tasks[0]

            pipeline.close()
            await asyncio.sleep(0)  # permite que el event loop procese la cancelacion

            assert task.cancelled() or task.done(), (
                "Task must be in cancelled or done state after close()"
            )
            assert task not in pipeline._playback_tasks, (
                "Task must be removed from _playback_tasks by close()"
            )
    finally:
        release.set()
        audio_exec.shutdown(wait=True, cancel_futures=True)


# ---------------------------------------------------------------------------
# T10 — Aislamiento de mocks: las funciones de IO estan parcheadas correctamente
# ---------------------------------------------------------------------------

def test_t10_isolation_patch_targets_are_correct() -> None:
    """T10: Verify that IO patch targets are callable in the production module."""
    from src.interaction import conversation_manager as cm

    # Las funciones que los tests parchean deben existir en el modulo de produccion
    assert callable(cm._run_piper_synthesis), (
        "_run_piper_synthesis must be patchable at module level"
    )
    assert callable(cm._play_audio_alsa), (
        "_play_audio_alsa must be patchable at module level"
    )

    # El cliente HTTP mock debe proveer un coroutine en post() para que asyncio.wait_for funcione
    http_mock = _make_cloud_http()
    assert isinstance(http_mock, AsyncMock), "HTTP client must be AsyncMock"
    assert isinstance(http_mock.post, AsyncMock), "client.post must be AsyncMock (awaitable)"

    # La respuesta mock debe contener bytes validos para np.frombuffer(..., dtype=np.int16)
    response = http_mock.post.return_value
    assert isinstance(response.content, bytes), "mock response.content must be bytes"
    pcm = np.frombuffer(response.content, dtype=np.int16)
    assert pcm.dtype == np.int16, "PCM mock data must be parseable as int16"

    # Verificar que modulos de hardware no han sido cargados como efecto colateral
    import sys
    for name in ("sounddevice", "piper", "faster_whisper", "ollama"):
        assert name not in sys.modules, f"Hardware module '{name}' must not be loaded"


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
