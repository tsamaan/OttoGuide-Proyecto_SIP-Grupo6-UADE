from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any, Optional

import httpx


@dataclass(frozen=True, slots=True)
class FactoryRestHealth:
    # @TASK: Representar resultado del handshake REST de fabrica
    # @INPUT: Estado HTTP, latencia y error opcional
    # @OUTPUT: Snapshot serializable para /status
    # @CONTEXT: Fuente secundaria de diagnostico; no controla locomocion
    # @SECURITY: No incluye payload sensible ni credenciales
    enabled: bool
    reachable: bool
    base_url: str
    endpoint: str
    status_code: Optional[int]
    latency_ms: Optional[float]
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        # @TASK: Convertir healthcheck a dict JSON-safe
        # @INPUT: Sin parametros
        # @OUTPUT: dict serializable
        # @CONTEXT: Usado por routers FastAPI sin acoplarse a dataclasses
        return asdict(self)


class UnitreeFactoryRestClient:
    _instance: Optional["UnitreeFactoryRestClient"] = None
    _instance_lock: Lock = Lock()

    def __init__(
        self,
        *,
        base_url: str = "http://192.168.12.1:9991",
        timeout_s: float = 0.35,
        enabled: bool = False,
    ) -> None:
        # @TASK: Inicializar cliente REST read-only del plano de fabrica
        # @INPUT: base_url, timeout_s, enabled
        # @OUTPUT: Cliente listo para healthcheck con timeout estricto
        # @CONTEXT: Singleton de conexion para diagnostico Unitree Go APK
        # @SECURITY: Solo se permite GET /con_check; sin endpoints de comando
        if timeout_s <= 0:
            raise ValueError("timeout_s debe ser mayor que 0.")
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._enabled = enabled

    @classmethod
    def get_instance(
        cls,
        *,
        base_url: str = "http://192.168.12.1:9991",
        timeout_s: float = 0.35,
        enabled: bool = False,
    ) -> "UnitreeFactoryRestClient":
        # @TASK: Obtener singleton REST de fabrica
        # @INPUT: base_url, timeout_s, enabled
        # @OUTPUT: Instancia unica por proceso
        # @CONTEXT: Patron Singleton reservado a conexiones de red
        # @SECURITY: Lock evita doble inicializacion concurrente
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(
                    base_url=base_url,
                    timeout_s=timeout_s,
                    enabled=enabled,
                )
            return cls._instance

    async def con_check(self) -> FactoryRestHealth:
        # @TASK: Ejecutar handshake read-only contra /con_check
        # @INPUT: Sin parametros
        # @OUTPUT: FactoryRestHealth con reachability y latencia
        # @CONTEXT: Endpoint derivado del APK Unitree Go v1.12.7
        # STEP 1: Retornar disabled sin I/O si el diagnostico no esta habilitado
        # STEP 2: Enviar GET /con_check con timeout estricto
        # STEP 3: Medir latencia y clasificar HTTP 2xx como reachable
        # @SECURITY: Prohibido emitir POST o paquetes de control de fabrica
        if not self._enabled:
            return FactoryRestHealth(
                enabled=False,
                reachable=False,
                base_url=self._base_url,
                endpoint="/con_check",
                status_code=None,
                latency_ms=None,
                error="factory diagnostics disabled",
            )

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.get(f"{self._base_url}/con_check")
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return FactoryRestHealth(
                enabled=True,
                reachable=200 <= response.status_code < 300,
                base_url=self._base_url,
                endpoint="/con_check",
                status_code=response.status_code,
                latency_ms=round(elapsed_ms, 3),
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return FactoryRestHealth(
                enabled=True,
                reachable=False,
                base_url=self._base_url,
                endpoint="/con_check",
                status_code=None,
                latency_ms=round(elapsed_ms, 3),
                error=f"{type(exc).__name__}: {exc}",
            )


__all__ = [
    "FactoryRestHealth",
    "UnitreeFactoryRestClient",
]
