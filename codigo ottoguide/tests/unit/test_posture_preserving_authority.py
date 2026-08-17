"""Static and dynamic regressions for exclusive operator posture authority."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hardware.real_adapter import UnitreeG1Adapter


@pytest.mark.asyncio
async def test_real_stop_motion_invokes_stopmove_exactly_once() -> None:
    adapter = UnitreeG1Adapter(network_interface="eth0")
    client = MagicMock()
    client.StopMove.return_value = 0
    adapter._sdk_client = client
    adapter._initialized = True

    await adapter.stop_motion()

    client.StopMove.assert_called_once_with()
    for forbidden in ("Damp", "Start", "StandUp", "BalanceStand"):
        getattr(client, forbidden).assert_not_called()


def test_initialize_source_contains_no_posture_command() -> None:
    source = Path(UnitreeG1Adapter.__module__.replace(".", "/") + ".py")
    text = source.read_text(encoding="utf-8")
    initialize = text.split("async def initialize", 1)[1].split("async def move", 1)[0]
    assert '"Damp"' not in initialize
    assert '"Start"' not in initialize
    assert "StandUp" not in initialize
    assert "BalanceStand" not in initialize


@pytest.mark.asyncio
async def test_stop_motion_timeout_is_bounded_by_sdk_invoker() -> None:
    adapter = UnitreeG1Adapter(network_interface="eth0")
    client = MagicMock()
    client.StopMove.side_effect = lambda: None
    adapter._sdk_client = client
    adapter._initialized = True
    await asyncio.wait_for(adapter.stop_motion(), timeout=1.0)


def test_programmatic_posture_methods_are_not_exposed() -> None:
    adapter = UnitreeG1Adapter(network_interface="eth0")
    for forbidden in ("damp", "stand", "emergency_stop"):
        assert not hasattr(adapter, forbidden)
