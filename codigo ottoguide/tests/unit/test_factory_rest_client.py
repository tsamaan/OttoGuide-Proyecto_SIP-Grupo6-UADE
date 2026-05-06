from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.infrastructure.unitree import UnitreeFactoryRestClient


@pytest.mark.asyncio
async def test_factory_rest_client_disabled_is_read_only() -> None:
    # @TASK: Validar diagnostico factory deshabilitado
    # @INPUT: Cliente con enabled=False
    # @OUTPUT: Healthcheck sin I/O y con reachable=False
    # @CONTEXT: Modo seguro por defecto para RC1_LOCKED
    # @SECURITY: No abre sockets ni emite paquetes de control
    client = UnitreeFactoryRestClient(
        base_url="http://192.168.12.1:9991",
        timeout_s=0.01,
        enabled=False,
    )

    health = await client.con_check()

    assert health.enabled is False
    assert health.reachable is False
    assert health.endpoint == "/con_check"
    assert health.status_code is None


def test_factory_rest_singleton_keeps_connection_scope() -> None:
    # @TASK: Validar Singleton de conexion REST factory
    # @INPUT: Dos solicitudes de instancia
    # @OUTPUT: Mismo objeto retornado
    # @CONTEXT: Singleton reservado a conexiones de red
    # @SECURITY: Evita pools/clientes duplicados por proceso
    UnitreeFactoryRestClient._instance = None

    first = UnitreeFactoryRestClient.get_instance(enabled=False)
    second = UnitreeFactoryRestClient.get_instance(enabled=False)

    assert first is second
    UnitreeFactoryRestClient._instance = None
