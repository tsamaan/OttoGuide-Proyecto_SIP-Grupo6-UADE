"""Regresiones offline para la fuente única de interfaz DDS del adaptador real."""

from __future__ import annotations

import os
import sys
import types
from unittest.mock import patch

import pytest

from config import settings as settings_module
from config.settings import Settings
from hardware.real_adapter import UnitreeG1Adapter


def test_factory_injects_settings_interface_when_shell_env_is_absent(monkeypatch) -> None:
    configured = Settings(
        ROBOT_MODE="real",
        ROBOT_NETWORK_INTERFACE="eth0",
        _env_file=None,
    )
    monkeypatch.delenv("ROBOT_NETWORK_INTERFACE", raising=False)
    monkeypatch.setattr(settings_module, "get_settings", lambda: configured)

    adapter = settings_module.get_hardware_adapter()

    assert os.environ.get("ROBOT_NETWORK_INTERFACE") is None
    assert adapter._network_interface == "eth0"


def test_constructor_is_keyword_only_and_normalizes_whitespace() -> None:
    with pytest.raises(TypeError):
        UnitreeG1Adapter("eth0")  # type: ignore[misc]

    adapter = UnitreeG1Adapter(network_interface="  eth0\t")
    assert adapter._network_interface == "eth0"


def test_empty_interface_fails_before_sdk_import() -> None:
    sys.modules.pop("unitree_sdk2py", None)

    with pytest.raises(ValueError, match="^ROBOT_NETWORK_INTERFACE_EMPTY$"):
        UnitreeG1Adapter(network_interface="   ")

    assert "unitree_sdk2py" not in sys.modules


def test_constructor_does_not_consult_environment() -> None:
    with patch.dict(os.environ, {"ROBOT_NETWORK_INTERFACE": "poison0"}, clear=False):
        adapter = UnitreeG1Adapter(network_interface="eth0")

    assert adapter._network_interface == "eth0"


@pytest.mark.asyncio
async def test_initialize_passes_exact_interface_and_only_calls_init(monkeypatch) -> None:
    calls: list[tuple[object, ...]] = []

    def channel_factory_initialize(domain_id, network_interface):
        calls.append(("ChannelFactoryInitialize", domain_id, network_interface))

    class FakeLocoClient:
        def __init__(self):
            calls.append(("LocoClient",))

        def Init(self):
            calls.append(("Init",))

    channel_module = types.ModuleType("unitree_sdk2py.core.channel")
    channel_module.ChannelFactoryInitialize = channel_factory_initialize
    loco_module = types.ModuleType("unitree_sdk2py.g1.loco.g1_loco_client")
    loco_module.LocoClient = FakeLocoClient

    monkeypatch.setitem(sys.modules, "unitree_sdk2py", types.ModuleType("unitree_sdk2py"))
    monkeypatch.setitem(sys.modules, "unitree_sdk2py.core", types.ModuleType("unitree_sdk2py.core"))
    monkeypatch.setitem(sys.modules, "unitree_sdk2py.core.channel", channel_module)
    monkeypatch.setitem(sys.modules, "unitree_sdk2py.g1", types.ModuleType("unitree_sdk2py.g1"))
    monkeypatch.setitem(sys.modules, "unitree_sdk2py.g1.loco", types.ModuleType("unitree_sdk2py.g1.loco"))
    monkeypatch.setitem(sys.modules, "unitree_sdk2py.g1.loco.g1_loco_client", loco_module)

    adapter = UnitreeG1Adapter(network_interface="eth0")
    await adapter.initialize()

    assert calls == [
        ("ChannelFactoryInitialize", 0, "eth0"),
        ("LocoClient",),
        ("Init",),
    ]
    assert adapter._initialized is True
    assert adapter._executor is not None
    adapter._executor.shutdown(wait=True)


@pytest.mark.parametrize("mode", ["mock", "demo"])
def test_mock_and_demo_do_not_import_unitree_sdk(mode, monkeypatch) -> None:
    for name in tuple(sys.modules):
        if name == "unitree_sdk2py" or name.startswith("unitree_sdk2py."):
            sys.modules.pop(name, None)

    configured = Settings(ROBOT_MODE=mode, _env_file=None)
    monkeypatch.setattr(settings_module, "get_settings", lambda: configured)

    settings_module.get_hardware_adapter()

    assert not any(
        name == "unitree_sdk2py" or name.startswith("unitree_sdk2py.")
        for name in sys.modules
    )
