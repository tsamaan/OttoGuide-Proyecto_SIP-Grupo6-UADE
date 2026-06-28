from __future__ import annotations

import asyncio
import ast
import json
import subprocess
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from src.interaction import conversation_manager as cm
from src.interaction.conversation_manager import (
    ConversationManager,
    ConversationResponse,
    LocalNLPPipeline,
)
from src.interaction import tts_unitree_client as tts


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE = "src.interaction.conversation_manager"


def _make_pipeline() -> tuple[LocalNLPPipeline, ThreadPoolExecutor, ThreadPoolExecutor]:
    cpu_executor = ThreadPoolExecutor(max_workers=1)
    audio_executor = ThreadPoolExecutor(max_workers=1)
    pipeline = LocalNLPPipeline(cpu_executor=cpu_executor, audio_executor=audio_executor)
    return pipeline, cpu_executor, audio_executor


async def _finish_pipeline(
    pipeline: LocalNLPPipeline,
    *executors: ThreadPoolExecutor,
    release_events: tuple[asyncio.Event, ...] = (),
) -> None:
    for event in release_events:
        event.set()
    tasks = list(pipeline._playback_tasks)
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    pipeline.close()
    for executor in executors:
        executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.asyncio
async def test_audio_char_001_current_conversation_path_uses_local_pipeline_not_tts_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[AUDIO-CHAR-001] Characterizes the current local TTS path and factory non-wiring."""
    main_ast = ast.parse((PROJECT_ROOT / "main.py").read_text(encoding="utf-8"))
    factory_fn = next(
        node
        for node in main_ast.body
        if isinstance(node, ast.FunctionDef) and node.name == "_get_conversation_manager_stub"
    )
    calls = [
        node.func.id
        for node in ast.walk(factory_fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]

    assert "LocalNLPPipeline" in calls
    assert "ConversationManager" in calls
    assert "tts_adapter_factory" not in calls

    factory_sentinel = MagicMock(side_effect=AssertionError("tts_adapter_factory is not wired"))
    monkeypatch.setattr(tts, "tts_adapter_factory", factory_sentinel)

    local_strategy = MagicMock(spec=LocalNLPPipeline)
    local_strategy.synthesize_and_play = AsyncMock()
    local_strategy.close = MagicMock()
    manager = ConversationManager(
        local_strategy=local_strategy,
        llm_client=MagicMock(),
        audio_bridge=MagicMock(),
    )
    manager._script = types.SimpleNamespace(
        waypoints=[
            types.SimpleNamespace(
                waypoint_id="I",
                interaction_type="scripted",
                script_text="Hola UADE",
            )
        ]
    )

    response = await manager.process_scripted_interaction("I")

    local_strategy.synthesize_and_play.assert_awaited_once_with("Hola UADE")
    factory_sentinel.assert_not_called()
    assert isinstance(response, ConversationResponse)
    assert response.answer_text == "Hola UADE"
    assert response.source_pipeline == "scripted"
    assert response.audio_stream_ready is True


def test_audio_char_002_piper_pcm_int16_to_float32_conversion_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[AUDIO-CHAR-002] Characterizes Piper int16 PCM to float32 conversion."""
    samples = np.array([-32768, -16384, -1, 0, 1, 16384, 32767], dtype=np.int16)
    chunks = [samples[:3].tobytes(), samples[3:].tobytes()]
    load_calls: list[str] = []
    synth_texts: list[str] = []

    class FakeVoice:
        def synthesize_stream_raw(self, text: str):
            synth_texts.append(text)
            return iter(chunks)

    class FakePiperVoice:
        @staticmethod
        def load(model_path: str) -> FakeVoice:
            load_calls.append(model_path)
            return FakeVoice()

    fake_piper = types.SimpleNamespace(PiperVoice=FakePiperVoice)
    monkeypatch.setitem(sys.modules, "piper", fake_piper)

    result = cm._run_piper_synthesis("x", "fake-model.onnx", cm.AUDIO_SAMPLE_RATE)
    result_with_longer_text = cm._run_piper_synthesis(
        "texto mas largo sin cambiar los bytes fake", "fake-model.onnx", cm.AUDIO_SAMPLE_RATE
    )

    expected = samples.astype(np.float32) / 32768.0
    assert load_calls == ["fake-model.onnx", "fake-model.onnx"]
    assert synth_texts == ["x", "texto mas largo sin cambiar los bytes fake"]
    assert result.dtype == np.float32
    assert result.shape == (7,)
    np.testing.assert_array_equal(result, expected)
    np.testing.assert_array_equal(result_with_longer_text, expected)
    assert float(result.min()) == -1.0
    assert float(result.max()) == np.float32(32767 / 32768.0)


@pytest.mark.asyncio
async def test_audio_char_003_synthesize_passes_same_pcm_values_to_alsa_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[AUDIO-CHAR-003] Characterizes the PCM buffer handed from synthesis to playback."""
    pipeline, cpu_executor, audio_executor = _make_pipeline()
    captured: dict[str, object] = {}
    playback_entered = asyncio.Event()
    pcm = np.array([0.0, -0.5, 0.25], dtype=np.float32)

    async def fake_run_alsa(pcm_arg, sample_rate, block_size):
        captured["pcm"] = pcm_arg
        captured["sample_rate"] = sample_rate
        captured["block_size"] = block_size
        playback_entered.set()

    monkeypatch.setattr(cm, "_run_piper_synthesis", MagicMock(return_value=pcm))
    monkeypatch.setattr(pipeline, "_run_alsa_playback", fake_run_alsa)

    try:
        await pipeline.synthesize_and_play("hola")
        await asyncio.wait_for(playback_entered.wait(), timeout=1.0)
        tasks = list(pipeline._playback_tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # task.done() being True after gather() does not guarantee that
        # add_done_callback(_on_playback_done) has already run: callback
        # dispatch order relative to gather()'s own return is scheduler-
        # dependent (observed: always already run on 3.10, never yet run on
        # 3.12 for this exact awaited-Event-then-gather shape). Yielding the
        # loop once is the deterministic way to wait for any callback queued
        # via loop.call_soon() during the task's last step.
        await asyncio.sleep(0)

        assert captured["pcm"] is pcm
        np.testing.assert_array_equal(captured["pcm"], pcm)
        assert captured["sample_rate"] == cm.AUDIO_SAMPLE_RATE
        assert captured["block_size"] == cm.AUDIO_BLOCK_SIZE
        assert pipeline._playback_tasks == set()
    finally:
        await _finish_pipeline(pipeline, cpu_executor, audio_executor)


def test_audio_char_004_tts_adapter_factory_current_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[AUDIO-CHAR-004] Characterizes the current tts_adapter_factory mapping."""
    constructed: list[str] = []

    class UnitreeSentinel:
        def __init__(self) -> None:
            constructed.append("unitree")

    class PiperSentinel:
        def __init__(self) -> None:
            constructed.append("piper")

    monkeypatch.setattr(tts, "UnitreeTTSAdapter", UnitreeSentinel)
    monkeypatch.setattr(tts, "PiperTTSAdapter", PiperSentinel)

    assert isinstance(tts.tts_adapter_factory(robot_mode="real"), UnitreeSentinel)
    for mode in ("mock", "sim", "demo", "unexpected"):
        assert isinstance(tts.tts_adapter_factory(robot_mode=mode), PiperSentinel)

    assert constructed == ["unitree", "piper", "piper", "piper", "piper"]
    assert not any(name.startswith("unitree_sdk2py") for name in sys.modules)


def test_audio_char_005_local_interaction_imports_do_not_require_unitree_sdk() -> None:
    """[AUDIO-CHAR-005] Characterizes local interaction imports without Unitree SDK."""
    probe = """
import concurrent.futures
import json
import sys

from src.interaction import conversation_manager as cm
from src.interaction import tts_unitree_client as tts

cpu = concurrent.futures.ThreadPoolExecutor(max_workers=1)
audio = concurrent.futures.ThreadPoolExecutor(max_workers=1)
pipeline = cm.LocalNLPPipeline(cpu_executor=cpu, audio_executor=audio)
adapter = tts.UnitreeTTSAdapter()
pipeline.close()
cpu.shutdown(wait=True, cancel_futures=True)
audio.shutdown(wait=True, cancel_futures=True)
print(json.dumps({
    "sdk_loaded": any(name.startswith("unitree_sdk2py") for name in sys.modules),
    "pipeline_type": type(pipeline).__name__,
    "adapter_type": type(adapter).__name__,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=3.0,
        check=True,
    )
    data = json.loads(completed.stdout)

    assert data == {
        "sdk_loaded": False,
        "pipeline_type": "LocalNLPPipeline",
        "adapter_type": "UnitreeTTSAdapter",
    }


@pytest.mark.asyncio
async def test_audio_char_008_synthesis_failure_creates_no_playback_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[AUDIO-CHAR-008] Characterizes synthesis failure before playback task creation."""
    pipeline, cpu_executor, audio_executor = _make_pipeline()
    playback_spy = MagicMock()

    def fail_synthesis(*args):
        raise RuntimeError("synthetic synthesis failure")

    monkeypatch.setattr(cm, "_run_piper_synthesis", fail_synthesis)
    monkeypatch.setattr(cm, "_play_audio_alsa", playback_spy)

    try:
        with pytest.raises(RuntimeError, match="synthetic synthesis failure"):
            await pipeline.synthesize_and_play("fallo")

        playback_spy.assert_not_called()
        assert pipeline._playback_tasks == set()
    finally:
        await _finish_pipeline(pipeline, cpu_executor, audio_executor)


@pytest.mark.asyncio
async def test_audio_char_009_cancelled_playback_task_state_and_set_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[AUDIO-CHAR-009] Characterizes observable cancellation of a playback Task."""
    pipeline, cpu_executor, audio_executor = _make_pipeline()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def controlled_playback(*args):
        entered.set()
        await release.wait()

    monkeypatch.setattr(cm, "_run_piper_synthesis", MagicMock(return_value=np.zeros(3, dtype=np.float32)))
    monkeypatch.setattr(pipeline, "_run_alsa_playback", controlled_playback)

    try:
        await pipeline.synthesize_and_play("cancelar")
        await asyncio.wait_for(entered.wait(), timeout=1.0)
        tasks = list(pipeline._playback_tasks)
        assert len(tasks) == 1
        task = tasks[0]

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        assert task.cancelled()
        assert task not in pipeline._playback_tasks
        assert pipeline._playback_tasks == set()
    finally:
        release.set()
        await _finish_pipeline(pipeline, cpu_executor, audio_executor, release_events=(release,))


@pytest.mark.asyncio
async def test_audio_char_010_current_runtime_allows_concurrent_playback_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[AUDIO-CHAR-010] Characterizes current coexistence of playback Tasks."""
    pipeline, cpu_executor, audio_executor = _make_pipeline()
    entered_count = 0
    both_entered = asyncio.Event()
    release = asyncio.Event()
    captured_pcm: list[np.ndarray] = []
    synthesis_calls: list[str] = []
    pcm_values = [
        np.array([1.0], dtype=np.float32),
        np.array([2.0], dtype=np.float32),
    ]

    def fake_synthesis(text: str, *args):
        index = len(synthesis_calls)
        synthesis_calls.append(text)
        return pcm_values[index]

    async def controlled_playback(pcm_arg, *args):
        nonlocal entered_count
        captured_pcm.append(pcm_arg)
        entered_count += 1
        if entered_count == 2:
            both_entered.set()
        await release.wait()

    monkeypatch.setattr(cm, "_run_piper_synthesis", fake_synthesis)
    monkeypatch.setattr(pipeline, "_run_alsa_playback", controlled_playback)

    try:
        await pipeline.synthesize_and_play("uno")
        await pipeline.synthesize_and_play("dos")
        await asyncio.wait_for(both_entered.wait(), timeout=1.0)

        assert len(pipeline._playback_tasks) == 2
        assert sorted(task.get_name() for task in pipeline._playback_tasks) == [
            "tts-alsa-playback",
            "tts-alsa-playback",
        ]
        assert synthesis_calls == ["uno", "dos"]
        assert len(captured_pcm) == len(pcm_values)
        for captured, expected in zip(captured_pcm, pcm_values):
            np.testing.assert_array_equal(captured, expected)

        release.set()
        await asyncio.gather(*list(pipeline._playback_tasks), return_exceptions=True)
        assert pipeline._playback_tasks == set()
    finally:
        release.set()
        await _finish_pipeline(pipeline, cpu_executor, audio_executor, release_events=(release,))


@pytest.mark.asyncio
async def test_audio_char_011_playback_lifecycle_observable_only_via_task_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[AUDIO-CHAR-011] Characterizes playback lifecycle observability through task set."""
    pipeline, cpu_executor, audio_executor = _make_pipeline()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def controlled_playback(*args):
        entered.set()
        await release.wait()

    monkeypatch.setattr(cm, "_run_piper_synthesis", MagicMock(return_value=np.zeros(4, dtype=np.float32)))
    monkeypatch.setattr(pipeline, "_run_alsa_playback", controlled_playback)

    try:
        assert not hasattr(pipeline, "is_speaking")
        assert not hasattr(pipeline, "speaking")

        await pipeline.synthesize_and_play("observar")
        await asyncio.wait_for(entered.wait(), timeout=1.0)
        assert len(pipeline._playback_tasks) == 1

        release.set()
        await asyncio.gather(*list(pipeline._playback_tasks), return_exceptions=True)
        assert pipeline._playback_tasks == set()
    finally:
        release.set()
        await _finish_pipeline(pipeline, cpu_executor, audio_executor, release_events=(release,))
