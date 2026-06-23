"""
Arranca y frena los procesos del robot (recorrido y charla).

En MOCK_MODE solo se actualiza el estado y se loguea, asi todo el flujo web
funciona sin sensores ni robot. Cuando MOCK_MODE=false, lanza los procesos
reales via subprocess.
"""
import logging
import signal
import subprocess
import time

from app.config import settings
from app.services.robot_state import state

log = logging.getLogger("ottoguide")

# ---------------------------------------------------------------------------
# Handles de los procesos reales (solo se usan cuando MOCK_MODE=false)
# ---------------------------------------------------------------------------
_tour_proc: subprocess.Popen | None = None
_chat_proc: subprocess.Popen | None = None


def _is_alive(proc: subprocess.Popen | None) -> bool:
    """Devuelve True si el proceso existe y sigue corriendo."""
    return proc is not None and proc.poll() is None


def _kill_proc(proc: subprocess.Popen, label: str, timeout: float = 5.0):
    """Envia SIGINT, espera `timeout` segundos y, si no murio, SIGKILL."""
    try:
        proc.send_signal(signal.SIGINT)
        log.info("[%s] SIGINT enviado (pid=%d)", label, proc.pid)
        try:
            proc.wait(timeout=timeout)
            log.info("[%s] proceso termino tras SIGINT", label)
        except subprocess.TimeoutExpired:
            proc.kill()
            log.warning("[%s] proceso no respondio a SIGINT; SIGKILL enviado", label)
            proc.wait(timeout=3)
    except ProcessLookupError:
        log.debug("[%s] proceso ya no existia", label)
    except Exception:
        log.exception("[%s] error al frenar proceso", label)


# ---------------------------------------------------------------------------
# Acciones publicas
# ---------------------------------------------------------------------------

def start_tour():
    """Inicia el orquestador completo (movimiento + recorrido)."""
    global _tour_proc

    if not settings.MOCK_MODE:
        if _is_alive(_tour_proc):
            log.warning("[recorrido] ya hay un proceso corriendo (pid=%d)", _tour_proc.pid)
            return state.snapshot()

        try:
            # TODO (D2 alternativa): Si se confirma que la API HTTP del robot
            #   existe (src/api/server.py, ej. 127.0.0.1:8000), reemplazar
            #   este subprocess por:
            #       import httpx
            #       httpx.post("http://127.0.0.1:8000/tour/start")
            _tour_proc = subprocess.Popen(
                ["./tools/hil/ottoguide-map", "start"],
                cwd=settings.ROBOT_REPO_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            log.info(
                "[recorrido] ottoguide-map start lanzado (pid=%d, cwd=%s)",
                _tour_proc.pid,
                settings.ROBOT_REPO_DIR,
            )
        except Exception:
            log.exception("[recorrido] fallo al lanzar ottoguide-map start")

    # TODO (D5): Si ottoguide-map soporta un subcomando "status", implementar
    # un polling periodico (ej. threading.Timer cada N segundos) que detecte
    # el fin del recorrido y auto-habilite state.llm_enabled = True.
    # Por ahora, el LLM solo se habilita al llamar manualmente a start_chat().
    # Esto NO afecta al resto de la integracion.

    state.set_tour()
    log.info("[recorrido] iniciado (mock=%s)", settings.MOCK_MODE)
    return state.snapshot()


def start_chat():
    """Inicia solo el pipeline conversacional (pilar IA: otto_pipeline)."""
    global _chat_proc

    if not settings.MOCK_MODE:
        if _is_alive(_chat_proc):
            log.warning("[charla] ya hay un proceso corriendo (pid=%d)", _chat_proc.pid)
            return state.snapshot()

        try:
            # TODO: confirmar ruta exacta de otto_pipeline en el robot.
            #   Si no esta en $PATH, setear OTTO_PIPELINE_BIN con la ruta absoluta.
            _chat_proc = subprocess.Popen(
                [settings.OTTO_PIPELINE_BIN],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            log.info(
                "[charla] otto_pipeline lanzado (pid=%d, bin=%s)",
                _chat_proc.pid,
                settings.OTTO_PIPELINE_BIN,
            )
        except Exception:
            log.exception("[charla] fallo al lanzar otto_pipeline")

    state.set_chat()
    log.info("[charla] iniciada (mock=%s)", settings.MOCK_MODE)
    return state.snapshot()


def stop_all():
    """Frena lo que este corriendo (recorrido o charla)."""
    global _tour_proc, _chat_proc

    prev = state.mode

    if not settings.MOCK_MODE:
        # Frenar charla: SIGINT al proceso otto_pipeline
        if _is_alive(_chat_proc):
            _kill_proc(_chat_proc, "charla")
            _chat_proc = None

        # Frenar recorrido: ottoguide-map stop
        if _is_alive(_tour_proc):
            try:
                subprocess.run(
                    ["./tools/hil/ottoguide-map", "stop"],
                    cwd=settings.ROBOT_REPO_DIR,
                    timeout=10,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                log.info("[recorrido] ottoguide-map stop ejecutado")
            except Exception:
                log.exception("[recorrido] fallo al ejecutar ottoguide-map stop")
                # Fallback: matar el proceso directamente
                _kill_proc(_tour_proc, "recorrido")
            _tour_proc = None

    state.set_idle()
    log.info("[stop] ejecucion terminada (modo previo=%s)", prev)
    return state.snapshot()
