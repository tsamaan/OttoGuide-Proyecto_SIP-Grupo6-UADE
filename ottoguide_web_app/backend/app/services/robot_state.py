"""Estado global del robot, compartido entre endpoints."""
import threading


class RobotState:
    """
    mode:               idle | tour | chat
    running:            hay algo ejecutandose
    llm_enabled:        el LLM quedo habilitado (lo habilita el orquestador al terminar el recorrido)
    conversation_state: hibernacion | escuchando | procesando  (solo aplica en modo chat)
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.mode = "idle"
        self.running = False
        self.llm_enabled = False
        self.conversation_state = "hibernacion"

    def set_tour(self):
        with self._lock:
            self.mode = "tour"
            self.running = True
            # El recorrido habilita el LLM al finalizar; mientras corre, todavia no.
            self.llm_enabled = False
            self.conversation_state = "hibernacion"

    def set_chat(self):
        with self._lock:
            self.mode = "chat"
            self.running = True
            self.llm_enabled = True
            self.conversation_state = "hibernacion"

    def set_idle(self):
        with self._lock:
            self.mode = "idle"
            self.running = False
            self.conversation_state = "hibernacion"

    def set_conversation_state(self, value: str):
        with self._lock:
            self.conversation_state = value

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "mode": self.mode,
                "running": self.running,
                "llm_enabled": self.llm_enabled,
                "conversation_state": self.conversation_state,
            }


state = RobotState()
