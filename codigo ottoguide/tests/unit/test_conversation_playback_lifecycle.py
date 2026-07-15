"""
@TASK: Verificar el ciclo de vida de tareas asyncio de reproduccion en LocalNLPPipeline y
       CloudNLPPipeline: correcto tipo pasado a create_task, registro en _playback_tasks,
       eliminacion al finalizar y cancelacion en close().
@INPUT: LocalNLPPipeline / CloudNLPPipeline con executors inyectados y funciones IO mockeadas
@OUTPUT: 11 casos de prueba (T01-T11); exit code 0 sin audio, red, Piper, Ollama ni hardware
@CONTEXT: Regresion para IA-RUNTIME-03; ejecutable en cualquier entorno Python 3.10+ con pytest.
@SECURITY: Sin I/O real; todas las llamadas a audio y HTTP estan sustituidas por mocks.

@NOTE (IA-CXX-R2A): las clases se obtienen del modulo importado una sola vez como `cm`
(identidad canonica), y todos los patches usan `patch.object(cm, ...)` en vez de
`patch("modulo.string", ...)`. Varios otros archivos de test (test_hardware_api.py,
test_vision_processor.py, test_u2_qr_lifespan_wiring.py) purgan y reimportan `src.*`
en algun punto de la coleccion/ejecucion completa de la suite. Un patch basado en
string re-resuelve el modulo via sys.modules en el momento en que se aplica el patch,
lo que puede ya no ser el mismo objeto que esta clase capturo en tiempo de coleccion.
patch.object sobre `cm` no tiene ese problema: opera sobre el objeto exacto que las
clases usan, sin volver a resolver nada. Esto elimino los 8 fallos heredados sin
tocar produccion; ver ROOT_CAUSE.md en el run root de
IA_CXX_R2A_CONVERSATION_PLAYBACK_TEST_ISOLATION para la evidencia reproducible.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from src.interaction import conversation_manager as cm

_LOGGER_NAME = cm.__name__


async def _await_tasks(tasks: list[asyncio.Task[None]], *, timeout: float = 2.0) -> None:
    """Esperar deterministicamente a que las tareas de reproduccion terminen.

    El timeout es una guarda contra un hang real, no el mecanismo de
    sincronizacion: la espera termina en cuanto todas las tareas finalizan,
    sin depender de cuanto tiempo real tome eso.
    """
    if not tasks:
        return
    await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)
    await asyncio.sleep(0)  # deja que el event loop procese los done callbacks ya disparados


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
    pipeline = cm.LocalNLPPipeline(cpu_executor=cpu_exec, audio_executor=audio_exec)
    try:
        with patch.object(cm, "_run_piper_synthesis", return_value=np.zeros(10, dtype=np.float32)) as mock_piper, \
             patch.object(cm, "_play_audio_alsa", return_value=None) as mock_alsa:
            await pipeline.synthesize_and_play("hola")
            await _await_tasks(list(pipeline._playback_tasks))
            assert mock_piper.called, "Mocked _run_piper_synthesis must be invoked, not the real function"
            assert mock_alsa.called, "Mocked _play_audio_alsa must be invoked, not the real function"
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
    pipeline = cm.CloudNLPPipeline(audio_executor=audio_exec, http_client=_make_cloud_http())
    try:
        with patch.object(cm, "_play_audio_alsa", return_value=None) as mock_alsa:
            await pipeline._cloud_tts_openai("hola")
            await _await_tasks(list(pipeline._playback_tasks))
            assert mock_alsa.called, "Mocked _play_audio_alsa must be invoked, not the real function"
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
    pipeline = cm.LocalNLPPipeline(cpu_executor=cpu_exec, audio_executor=audio_exec)
    try:
        with patch.object(cm, "_run_piper_synthesis", return_value=np.zeros(10, dtype=np.float32)), \
             patch.object(cm, "_play_audio_alsa", side_effect=blocking_alsa) as mock_alsa:
            await pipeline.synthesize_and_play("test")
            assert len(pipeline._playback_tasks) >= 1, "Task must be registered before completion"
            tasks = list(pipeline._playback_tasks)
            release.set()
            await _await_tasks(tasks)
            assert mock_alsa.called, "Mocked _play_audio_alsa must be invoked, not the real function"
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
    pipeline = cm.LocalNLPPipeline(cpu_executor=cpu_exec, audio_executor=audio_exec)
    try:
        with patch.object(cm, "_run_piper_synthesis", return_value=np.zeros(10, dtype=np.float32)) as mock_piper, \
             patch.object(cm, "_play_audio_alsa", return_value=None) as mock_alsa:
            await pipeline.synthesize_and_play("test")
            await _await_tasks(list(pipeline._playback_tasks))
            assert len(pipeline._playback_tasks) == 0, "Task must be removed after done callback"
            assert mock_piper.called and mock_alsa.called, (
                "Mocked IO functions must be invoked, not the real ones"
            )
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
    pipeline = cm.CloudNLPPipeline(audio_executor=audio_exec, http_client=_make_cloud_http())
    try:
        with patch.object(cm, "_play_audio_alsa", side_effect=blocking_alsa) as mock_alsa:
            await pipeline._cloud_tts_openai("test")
            assert len(pipeline._playback_tasks) >= 1, "Cloud task must be registered"
            tasks = list(pipeline._playback_tasks)
            release.set()
            await _await_tasks(tasks)
            assert len(pipeline._playback_tasks) == 0, "Cloud task must be removed after completion"
            assert mock_alsa.called, "Mocked _play_audio_alsa must be invoked, not the real function"
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
    pipeline = cm.LocalNLPPipeline(cpu_executor=cpu_exec, audio_executor=audio_exec)
    try:
        with patch.object(cm, "_run_piper_synthesis", return_value=np.zeros(10, dtype=np.float32)) as mock_piper, \
             patch.object(cm, "_play_audio_alsa", side_effect=failing_alsa) as mock_alsa, \
             caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            await pipeline.synthesize_and_play("test")
            await _await_tasks(list(pipeline._playback_tasks))

        assert mock_piper.called and mock_alsa.called, (
            "Mocked IO functions must be invoked, not the real ones"
        )
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
    pipeline = cm.LocalNLPPipeline(cpu_executor=cpu_exec, audio_executor=audio_exec)
    try:
        with patch.object(cm, "_run_piper_synthesis", return_value=np.zeros(10, dtype=np.float32)) as mock_piper, \
             patch.object(cm, "_play_audio_alsa", side_effect=blocking_alsa), \
             caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            await pipeline.synthesize_and_play("test")
            assert mock_piper.called, "Mocked _run_piper_synthesis must be invoked, not the real function"
            tasks = list(pipeline._playback_tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(0)  # un tick del loop para que el done callback vea la cancelacion

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
    pipeline = cm.LocalNLPPipeline(cpu_executor=cpu_exec, audio_executor=audio_exec)
    try:
        with patch.object(cm, "_run_piper_synthesis", return_value=np.zeros(10, dtype=np.float32)) as mock_piper, \
             patch.object(cm, "_play_audio_alsa", side_effect=blocking_alsa):
            await pipeline.synthesize_and_play("test")
            assert mock_piper.called, "Mocked _run_piper_synthesis must be invoked, not the real function"

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
    pipeline = cm.CloudNLPPipeline(audio_executor=audio_exec, http_client=_make_cloud_http())
    try:
        with patch.object(cm, "_play_audio_alsa", side_effect=blocking_alsa):
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
    """T10: Verify that IO patch targets are callable in the production module,
    belong to the same canonical module object the pipeline classes use, and
    that importing the module alone never loads hardware IO modules.

    The hardware-module check runs a clean subprocess that imports ONLY this
    module and reports which modules newly appear as a direct result -- unlike
    checking `sys.modules` membership in the current pytest process (which
    accumulates the history of every previously executed test), this cannot
    depend on what any other test did.
    """
    # Las funciones que los tests parchean deben existir en el modulo de produccion
    assert callable(cm._run_piper_synthesis), (
        "_run_piper_synthesis must be patchable at module level"
    )
    assert callable(cm._play_audio_alsa), (
        "_play_audio_alsa must be patchable at module level"
    )
    # Los targets parcheables deben pertenecer al MISMO objeto de modulo que las
    # clases usan -- no una resolucion de string independiente que podria
    # apuntar a otro objeto si algo purgo y reimporto src.* mientras tanto.
    assert (
        cm.LocalNLPPipeline.synthesize_and_play.__globals__["_run_piper_synthesis"]
        is cm._run_piper_synthesis
    ), "LocalNLPPipeline must resolve _run_piper_synthesis from the same module object as `cm`"

    # El cliente HTTP mock debe proveer un coroutine en post() para que asyncio.wait_for funcione
    http_mock = _make_cloud_http()
    assert isinstance(http_mock, AsyncMock), "HTTP client must be AsyncMock"
    assert isinstance(http_mock.post, AsyncMock), "client.post must be AsyncMock (awaitable)"

    # La respuesta mock debe contener bytes validos para np.frombuffer(..., dtype=np.int16)
    response = http_mock.post.return_value
    assert isinstance(response.content, bytes), "mock response.content must be bytes"
    pcm = np.frombuffer(response.content, dtype=np.int16)
    assert pcm.dtype == np.int16, "PCM mock data must be parseable as int16"

    # Verificar, en un subprocess limpio, que importar este modulo por si solo
    # no carga ningun modulo de hardware como efecto colateral.
    import json
    import pathlib
    import subprocess
    import sys as _sys

    repo_root = pathlib.Path(cm.__file__).resolve().parents[2]
    probe = (
        "import sys, json\n"
        "before = set(sys.modules)\n"
        "import src.interaction.conversation_manager\n"
        "after = set(sys.modules)\n"
        "print(json.dumps(sorted(after - before)))\n"
    )
    completed = subprocess.run(
        [_sys.executable, "-c", probe],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    newly_loaded = set(json.loads(completed.stdout))
    forbidden = {"sounddevice", "piper", "faster_whisper", "ollama"}
    leaked = newly_loaded & forbidden
    assert not leaked, (
        f"Importing conversation_manager alone must not load hardware modules; "
        f"loaded as a direct result of the import: {leaked}"
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
