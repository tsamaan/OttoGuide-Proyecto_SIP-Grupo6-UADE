"""
@TASK: Verificar interlock cloud air-gapped en ConversationManager y CloudNLPPipeline.
@INPUT: ConversationManager / CloudNLPPipeline con estrategias mockeadas
@OUTPUT: 18 casos de prueba (T01-T18); exit code 0 sin red, audio ni hardware
@CONTEXT: Regresion para la politica de interlock fail-closed:
          CLOUD_FALLBACK_ENABLED default=False; ROBOT_MODE=real bloquea cloud siempre;
          cloud deshabilitado: timeout/error -> respuesta segura local, sin swap_count, sin pipeline swap.
@SECURITY: Sin I/O real; todas las llamadas HTTP y audio estan sustituidas por mocks.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.interaction.conversation_manager import (
    CloudNLPPipeline,
    ConversationManager,
    ConversationRequest,
    ConversationResponse,
    LocalNLPPipeline,
)

_MODULE = "src.interaction.conversation_manager"

# ---------------------------------------------------------------------------
# Helpers de construccion
# ---------------------------------------------------------------------------

def _make_local_mock() -> MagicMock:
    m = MagicMock(spec=LocalNLPPipeline)
    m.generate = AsyncMock()
    m.synthesize_and_play = AsyncMock()
    m.transcribe = AsyncMock()
    m.close = MagicMock()
    return m


def _make_cloud_mock() -> MagicMock:
    m = MagicMock(spec=CloudNLPPipeline)
    m.generate = AsyncMock()
    m.close = MagicMock()
    return m


def _cm(*, cloud_fallback_enabled: bool = False, cloud_strategy=None, local=None) -> ConversationManager:
    return ConversationManager(
        local_strategy=local or _make_local_mock(),
        cloud_strategy=cloud_strategy,
        cloud_fallback_enabled=cloud_fallback_enabled,
    )


# ---------------------------------------------------------------------------
# T01 — CloudNLPPipeline.generate() raises RuntimeError when enabled=False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t01_cloud_pipeline_generate_blocked_when_disabled() -> None:
    """T01: CloudNLPPipeline.generate() raises RuntimeError immediately when enabled=False."""
    audio_exec = ThreadPoolExecutor(max_workers=1)
    try:
        pipeline = CloudNLPPipeline(enabled=False, audio_executor=audio_exec)
        with pytest.raises(RuntimeError, match="interlock"):
            await pipeline.generate(ConversationRequest(user_text="hola"))
    finally:
        audio_exec.shutdown(wait=True, cancel_futures=True)


# ---------------------------------------------------------------------------
# T02 — CloudNLPPipeline.generate() passes enabled guard when enabled=True
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t02_cloud_pipeline_generate_no_early_error_when_enabled() -> None:
    """T02: CloudNLPPipeline.generate() with enabled=True does not raise interlock error."""
    audio_exec = ThreadPoolExecutor(max_workers=1)
    try:
        pipeline = CloudNLPPipeline(
            enabled=True,
            openai_api_key="test-key",
            audio_executor=audio_exec,
        )
        http_mock = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "respuesta"}}]
        }
        mock_response.raise_for_status = MagicMock()
        http_mock.post = AsyncMock(return_value=mock_response)

        with patch(f"{_MODULE}.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=http_mock)
            pipeline._http_client = http_mock

            try:
                result = await pipeline.generate(ConversationRequest(user_text="hola"))
                assert result.source_pipeline == "cloud"
            except RuntimeError as exc:
                if "interlock" in str(exc):
                    raise
    finally:
        audio_exec.shutdown(wait=True, cancel_futures=True)


# ---------------------------------------------------------------------------
# T03 — ConversationManager accepts cloud_strategy=None when cloud_fallback_enabled=False
# ---------------------------------------------------------------------------

def test_t03_cm_accepts_no_cloud_strategy_when_disabled() -> None:
    """T03: ConversationManager can be created without cloud_strategy when cloud disabled."""
    cm = _cm(cloud_fallback_enabled=False, cloud_strategy=None)
    assert cm._cloud is None
    assert cm._cloud_fallback_enabled is False
    cm.close()


# ---------------------------------------------------------------------------
# T04 — ConversationManager raises ValueError when cloud_fallback_enabled=True and cloud_strategy=None
# ---------------------------------------------------------------------------

def test_t04_cm_raises_value_error_cloud_enabled_no_strategy() -> None:
    """T04: cloud_fallback_enabled=True with cloud_strategy=None raises ValueError."""
    with pytest.raises(ValueError, match="cloud_strategy"):
        ConversationManager(
            local_strategy=_make_local_mock(),
            cloud_strategy=None,
            cloud_fallback_enabled=True,
        )


# ---------------------------------------------------------------------------
# T05 — _safe_local_response returns expected ConversationResponse
# ---------------------------------------------------------------------------

def test_t05_safe_local_response_fields() -> None:
    """T05: _safe_local_response has source_pipeline=local and audio_stream_ready=False."""
    cm = _cm()
    resp = cm._safe_local_response()
    assert resp.source_pipeline == "local"
    assert resp.audio_stream_ready is False
    assert len(resp.answer_text) > 0
    cm.close()


# ---------------------------------------------------------------------------
# T06 — _cloud_fallback_text returns safe response when cloud_fallback_enabled=False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t06_cloud_fallback_text_blocked_when_disabled() -> None:
    """T06: _cloud_fallback_text returns safe response without calling cloud when disabled."""
    cloud_mock = _make_cloud_mock()
    cm = _cm(cloud_fallback_enabled=False, cloud_strategy=cloud_mock)
    resp = await cm._cloud_fallback_text("hola")
    cloud_mock.generate.assert_not_called()
    assert resp.source_pipeline == "local"
    assert resp.audio_stream_ready is False
    cm.close()


# ---------------------------------------------------------------------------
# T07 — _cloud_fallback_text returns safe response when cloud_strategy is None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t07_cloud_fallback_text_blocked_when_strategy_none() -> None:
    """T07: _cloud_fallback_text returns safe response when cloud_strategy is None."""
    cm = _cm(cloud_fallback_enabled=False, cloud_strategy=None)
    resp = await cm._cloud_fallback_text("hola")
    assert resp.source_pipeline == "local"
    assert resp.audio_stream_ready is False
    cm.close()


# ---------------------------------------------------------------------------
# T08 — process_interaction: STT timeout with cloud disabled → safe response, no cloud call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t08_process_interaction_stt_timeout_cloud_disabled() -> None:
    """T08: STT timeout with cloud disabled returns safe response without calling cloud."""
    import numpy as np

    local = _make_local_mock()
    local.transcribe = AsyncMock(side_effect=asyncio.TimeoutError())
    cloud_mock = _make_cloud_mock()

    cm = _cm(cloud_fallback_enabled=False, cloud_strategy=cloud_mock, local=local)
    # Force scripted path so process_interaction runs STT, not start_interactive_session
    cm._current_waypoint_interaction_type = "scripted"
    resp = await cm.process_interaction(
        np.zeros(100, dtype=np.float32),
        preferred_pipeline="local",
    )

    cloud_mock.generate.assert_not_called()
    assert resp.source_pipeline == "local"
    assert resp.audio_stream_ready is False
    cm.close()


# ---------------------------------------------------------------------------
# T09 — process_interaction: LLM timeout with cloud disabled → safe response, no cloud call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t09_process_interaction_llm_timeout_cloud_disabled() -> None:
    """T09: LLM timeout with cloud disabled returns safe response without calling cloud."""
    import numpy as np

    local = _make_local_mock()
    local.transcribe = AsyncMock(return_value="hola")
    local.generate = AsyncMock(side_effect=asyncio.TimeoutError())
    cloud_mock = _make_cloud_mock()

    cm = _cm(cloud_fallback_enabled=False, cloud_strategy=cloud_mock, local=local)
    # Force scripted path so process_interaction runs STT+LLM, not start_interactive_session
    cm._current_waypoint_interaction_type = "scripted"
    resp = await cm.process_interaction(
        np.zeros(100, dtype=np.float32),
        preferred_pipeline="local",
    )

    cloud_mock.generate.assert_not_called()
    assert resp.source_pipeline == "local"
    assert resp.audio_stream_ready is False
    cm.close()


# ---------------------------------------------------------------------------
# T10 — respond() with cloud disabled → safe response, no cloud call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t10_respond_cloud_disabled_returns_safe_response() -> None:
    """T10: respond() with cloud disabled returns safe response on local timeout."""
    local = _make_local_mock()
    local.generate = AsyncMock(side_effect=asyncio.TimeoutError())
    cloud_mock = _make_cloud_mock()

    cm = _cm(cloud_fallback_enabled=False, cloud_strategy=cloud_mock, local=local)
    resp = await cm.respond(ConversationRequest(user_text="consulta de prueba"))

    cloud_mock.generate.assert_not_called()
    assert resp.source_pipeline == "local"
    assert resp.audio_stream_ready is False
    cm.close()


# ---------------------------------------------------------------------------
# T11 — swap_count NOT incremented when cloud disabled and STT times out
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t11_swap_count_not_incremented_on_stt_timeout_cloud_disabled() -> None:
    """T11: swap_count stays 0 when cloud disabled and STT times out."""
    import numpy as np

    local = _make_local_mock()
    local.transcribe = AsyncMock(side_effect=asyncio.TimeoutError())

    cm = _cm(cloud_fallback_enabled=False, local=local)
    cm._current_waypoint_interaction_type = "scripted"
    assert cm.swap_count == 0

    await cm.process_interaction(np.zeros(100, dtype=np.float32))

    assert cm.swap_count == 0, "swap_count must not increment when cloud is disabled"
    cm.close()


# ---------------------------------------------------------------------------
# T12 — swap_count NOT incremented when cloud disabled and LLM times out
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t12_swap_count_not_incremented_on_llm_timeout_cloud_disabled() -> None:
    """T12: swap_count stays 0 when cloud disabled and LLM times out."""
    import numpy as np

    local = _make_local_mock()
    local.transcribe = AsyncMock(return_value="hola")
    local.generate = AsyncMock(side_effect=asyncio.TimeoutError())

    cm = _cm(cloud_fallback_enabled=False, local=local)
    cm._current_waypoint_interaction_type = "scripted"
    assert cm.swap_count == 0

    await cm.process_interaction(np.zeros(100, dtype=np.float32))

    assert cm.swap_count == 0, "swap_count must not increment when cloud is disabled"
    cm.close()


# ---------------------------------------------------------------------------
# T13 — active_pipeline NOT changed when cloud disabled and STT times out
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t13_active_pipeline_not_changed_on_stt_timeout_cloud_disabled() -> None:
    """T13: active_pipeline stays 'local' when cloud disabled and STT times out."""
    import numpy as np

    local = _make_local_mock()
    local.transcribe = AsyncMock(side_effect=asyncio.TimeoutError())

    cm = _cm(cloud_fallback_enabled=False, local=local)
    cm._current_waypoint_interaction_type = "scripted"
    assert cm.active_strategy_name == "local"

    await cm.process_interaction(np.zeros(100, dtype=np.float32))

    assert cm.active_strategy_name == "local", (
        "active_pipeline must not change to 'cloud' when cloud is disabled"
    )
    cm.close()


# ---------------------------------------------------------------------------
# T14 — active_pipeline NOT changed when cloud disabled and LLM times out
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t14_active_pipeline_not_changed_on_llm_timeout_cloud_disabled() -> None:
    """T14: active_pipeline stays 'local' when cloud disabled and LLM times out."""
    import numpy as np

    local = _make_local_mock()
    local.transcribe = AsyncMock(return_value="hola")
    local.generate = AsyncMock(side_effect=asyncio.TimeoutError())

    cm = _cm(cloud_fallback_enabled=False, local=local)
    cm._current_waypoint_interaction_type = "scripted"
    assert cm.active_strategy_name == "local"

    await cm.process_interaction(np.zeros(100, dtype=np.float32))

    assert cm.active_strategy_name == "local", (
        "active_pipeline must not change to 'cloud' when cloud is disabled"
    )
    cm.close()


# ---------------------------------------------------------------------------
# T15 — swap_count increments when cloud IS enabled and LLM times out
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t15_swap_count_increments_when_cloud_enabled_and_llm_times_out() -> None:
    """T15: swap_count increments and cloud is called when cloud enabled and LLM times out."""
    import numpy as np

    local = _make_local_mock()
    local.transcribe = AsyncMock(return_value="hola")
    local.generate = AsyncMock(side_effect=asyncio.TimeoutError())

    cloud_response = ConversationResponse(
        answer_text="respuesta cloud", source_pipeline="cloud", audio_stream_ready=True
    )
    cloud_mock = _make_cloud_mock()
    cloud_mock.generate = AsyncMock(return_value=cloud_response)

    cm = _cm(cloud_fallback_enabled=True, cloud_strategy=cloud_mock, local=local)
    cm._current_waypoint_interaction_type = "scripted"
    assert cm.swap_count == 0

    resp = await cm.process_interaction(np.zeros(100, dtype=np.float32))

    assert cm.swap_count == 1, "swap_count must increment when cloud is enabled and used"
    assert cm.active_strategy_name == "cloud"
    assert resp.source_pipeline == "cloud"
    cloud_mock.generate.assert_called_once()
    cm.close()


# ---------------------------------------------------------------------------
# T16 — respond() swap_count NOT incremented when cloud disabled
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t16_respond_swap_count_not_incremented_cloud_disabled() -> None:
    """T16: respond() swap_count stays 0 when cloud disabled and local times out."""
    local = _make_local_mock()
    local.generate = AsyncMock(side_effect=asyncio.TimeoutError())

    cm = _cm(cloud_fallback_enabled=False, local=local)
    assert cm.swap_count == 0

    await cm.respond(ConversationRequest(user_text="test"))

    assert cm.swap_count == 0, "swap_count must not increment when cloud is disabled"
    cm.close()


# ---------------------------------------------------------------------------
# T17 — ConversationManager.close() works when cloud_strategy is None
# ---------------------------------------------------------------------------

def test_t17_close_with_no_cloud_strategy() -> None:
    """T17: close() completes without error when cloud_strategy is None."""
    local = _make_local_mock()
    cm = _cm(cloud_fallback_enabled=False, local=local)
    assert cm._cloud is None
    cm.close()
    local.close.assert_called_once()


# ---------------------------------------------------------------------------
# T18 — swap_count increments and active_pipeline switches when cloud enabled and respond() times out
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t18_respond_swap_and_cloud_when_enabled() -> None:
    """T18: respond() increments swap_count and uses cloud when cloud enabled and local fails."""
    local = _make_local_mock()
    local.generate = AsyncMock(side_effect=asyncio.TimeoutError())

    cloud_response = ConversationResponse(
        answer_text="respuesta cloud", source_pipeline="cloud", audio_stream_ready=True
    )
    cloud_mock = _make_cloud_mock()
    cloud_mock.generate = AsyncMock(return_value=cloud_response)

    cm = _cm(cloud_fallback_enabled=True, cloud_strategy=cloud_mock, local=local)
    assert cm.swap_count == 0

    resp = await cm.respond(ConversationRequest(user_text="test"))

    assert cm.swap_count == 1
    assert cm.active_strategy_name == "cloud"
    assert resp.source_pipeline == "cloud"
    cloud_mock.generate.assert_called_once()
    cm.close()
