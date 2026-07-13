"""
@TASK: Resolver Settings.INTERACTION_RUNTIME_BACKEND en una instancia concreta de InteractionRuntimePort
@INPUT: Settings con INTERACTION_RUNTIME_BACKEND, INTERACTION_WORKER_PATH y timeouts INTERACTION_*
@OUTPUT: None si backend="disabled"; una unica JsonlInteractionWorkerSupervisor (sin iniciar) si
         backend="cxx_jsonl_mock"
@CONTEXT: Analogo a _build_navigation_bridge en main.py. No inicia el proceso (no llama start()),
          no importa hardware, no ejecuta modelos. main.py es responsable de invocar start() y
          de inyectar la instancia en TourOrchestrator/app.state.
@SECURITY: argv se construye sin shell (subprocess exec directo via asyncio.create_subprocess_exec
           dentro de JsonlInteractionWorkerSupervisor). Fail-closed: un backend desconocido o
           configuracion invalida lanza excepcion, nunca degrada silenciosamente a disabled.
"""
from __future__ import annotations

from typing import Optional

from src.interaction.jsonl_worker_supervisor import (
    JsonlInteractionWorkerSupervisor,
    JsonlWorkerSupervisorConfig,
)


def build_interaction_runtime(settings) -> Optional[JsonlInteractionWorkerSupervisor]:
    """
    @TASK: Construir (sin iniciar) el interaction runtime resuelto desde Settings
    @INPUT: settings — instancia de Settings ya validada via validate_interaction_runtime_config()
    @OUTPUT: None si INTERACTION_RUNTIME_BACKEND="disabled"; JsonlInteractionWorkerSupervisor
             construido (constructor puro, sin I/O) si "cxx_jsonl_mock"
    @CONTEXT: Invocado desde el lifespan de main.py, ANTES de await runtime.start().
    @SECURITY: No inicia el subproceso, no importa hardware ni modelos. argv resuelto de
               INTERACTION_WORKER_PATH como un unico argumento de programa (sin parseo de shell).

    STEP 1: backend="disabled" -> None, sin construir nada
    STEP 2: backend="cxx_jsonl_mock" -> construir JsonlWorkerSupervisorConfig con argv=(path,) y
            los timeouts INTERACTION_* de Settings; instanciar exactamente un supervisor
    STEP 3: backend desconocido -> ValueError (fail-closed, nunca silencioso)
    """
    # getattr defensivo: compatibilidad con test doubles preexistentes (SimpleNamespace en
    # tests/unit/test_navigation_runtime_selection.py) que no implementan este campo nuevo.
    # config.settings.Settings real SIEMPRE lo expone (default "disabled").
    backend = getattr(settings, "INTERACTION_RUNTIME_BACKEND", "disabled")

    if backend == "disabled":
        return None

    if backend == "cxx_jsonl_mock":
        config = JsonlWorkerSupervisorConfig(
            argv=(settings.INTERACTION_WORKER_PATH,),
            startup_timeout_s=settings.INTERACTION_STARTUP_TIMEOUT_S,
            heartbeat_timeout_s=settings.INTERACTION_HEARTBEAT_TIMEOUT_S,
            shutdown_timeout_s=settings.INTERACTION_SHUTDOWN_TIMEOUT_S,
        )
        return JsonlInteractionWorkerSupervisor(config)

    raise ValueError(f"INTERACTION_RUNTIME_BUILD_FAILED:unknown_backend:{backend}")


__all__ = ["build_interaction_runtime"]
