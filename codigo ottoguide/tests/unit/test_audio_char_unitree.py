from __future__ import annotations

import logging
import sys

import pytest

from src.interaction.tts_unitree_client import UnitreeTTSAdapter


def test_audio_char_012_unitree_tts_adapter_offline_fake_client_invokes_ttsmaker(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """[AUDIO-CHAR-012] Characterizes Unitree adapter behavior with an offline fake client."""
    sdk_modules_before = {name for name in sys.modules if name.startswith("unitree_sdk2py")}
    ttsmaker_calls: list[tuple[str, int]] = []

    class FakeClient:
        def TtsMaker(self, text: str, language: int) -> None:
            ttsmaker_calls.append((text, language))

    def fail_if_sdk_init_is_reached():
        pytest.fail("Unitree SDK initialization is not part of this offline characterization")

    adapter = UnitreeTTSAdapter(language=1)
    adapter._client = FakeClient()
    monkeypatch.setattr(UnitreeTTSAdapter, "_init_sdk_client", staticmethod(fail_if_sdk_init_is_reached))

    adapter._speak_sync("Hola UADE")

    assert ttsmaker_calls == [("Hola UADE", 1)]
    assert {name for name in sys.modules if name.startswith("unitree_sdk2py")} == sdk_modules_before

    class FailingClient:
        def TtsMaker(self, text: str, language: int) -> None:
            raise RuntimeError("offline fake failure")

    adapter._client = FailingClient()
    with caplog.at_level(logging.WARNING, logger="src.interaction.tts_unitree_client"):
        adapter._speak_sync("Falla controlada")

    assert any("Error en TtsMaker" in record.getMessage() for record in caplog.records)
    assert {name for name in sys.modules if name.startswith("unitree_sdk2py")} == sdk_modules_before
