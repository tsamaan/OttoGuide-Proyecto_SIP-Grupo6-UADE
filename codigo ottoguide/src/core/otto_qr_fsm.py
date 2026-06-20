from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml

from src.core.local_audio_player import LocalAudioPlayer
from src.core.qr_motion_driver import QRMotionDriver
from src.vision.qr_detector import QRDetector

LOGGER = logging.getLogger(__name__)


class OttoQRState(str, Enum):
    STARTUP = "startup"
    SCANNING = "scanning"
    APPROACH_DELAY = "approach_delay"
    STOPPED_FOR_STATION = "stopped_for_station"
    TURN_TO_STUDENTS = "turn_to_students"
    PLAYING_AUDIO = "playing_audio"
    TURN_TO_FRONT = "turn_to_front"
    COOLDOWN = "cooldown"
    FINAL_LLM = "final_llm"
    STOPPED = "stopped"
    EMERGENCY = "emergency"


@dataclass(frozen=True, slots=True)
class StartStation:
    id: str
    name: str
    audio_path: str
    turn_to_students_deg: float
    turn_to_front_deg: float


@dataclass(frozen=True, slots=True)
class QRStation:
    qr_value: str
    id: str
    name: str
    audio_path: str
    turn_to_students_deg: float
    turn_to_front_deg: float
    is_final: bool
    llm_zone_id: Optional[str] = None


class QRStationRegistry:
    """
    @TASK: Resolver dinámicamente una estación a partir del texto leído en el QR.
    @CONTEXT: No hay orden obligatorio; cada QR conocido dispara su propio audio.
    """

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.start: StartStation
        self.stations_by_qr: dict[str, QRStation] = {}
        self._load()

    def _load(self) -> None:
        data = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))

        start = data["start"]
        self.start = StartStation(
            id=str(start["id"]),
            name=str(start["name"]),
            audio_path=str(start["audio_path"]),
            turn_to_students_deg=float(start.get("turn_to_students_deg", 0)),
            turn_to_front_deg=float(start.get("turn_to_front_deg", 0)),
        )

        for qr_value, item in data["stations"].items():
            station = QRStation(
                qr_value=str(qr_value),
                id=str(item["id"]),
                name=str(item["name"]),
                audio_path=str(item["audio_path"]),
                turn_to_students_deg=float(item.get("turn_to_students_deg", 180)),
                turn_to_front_deg=float(item.get("turn_to_front_deg", -180)),
                is_final=bool(item.get("is_final", False)),
                llm_zone_id=item.get("llm_zone_id"),
            )
            self.stations_by_qr[station.qr_value] = station

    def resolve(self, qr_value: str) -> Optional[QRStation]:
        return self.stations_by_qr.get(qr_value)


class ConversationManagerLLMAdapter:
    """
    @TASK: Adaptar ConversationManager existente a la FSM QR para activar LLM final.
    @CONTEXT: Usa start_interactive_session() si existe; si no, cae a process_interaction().
    """

    def __init__(self, conversation_manager: object) -> None:
        self._conversation_manager = conversation_manager

    async def start_session(self, *, zone_id: str) -> None:
        set_zone = getattr(self._conversation_manager, "set_active_zone", None)
        if callable(set_zone):
            set_zone(zone_id)

        start_session = getattr(self._conversation_manager, "start_interactive_session", None)
        if callable(start_session):
            await start_session(zone_id)
            return

        process_interaction = getattr(self._conversation_manager, "process_interaction", None)
        if callable(process_interaction):
            await process_interaction(None, language="es")
            return

        LOGGER.warning("[QR_FSM] ConversationManager no expone sesión LLM interactiva.")


class OttoQRAsyncFSM:
    """
    @TASK: FSM asíncrona guiada únicamente por eventos QR.
    @CONTEXT: Si no hay QR o el QR es desconocido, Otto sigue avanzando sin error.
    @SECURITY: El loop de movimiento se detiene siempre en finally.
    """

    def __init__(
        self,
        *,
        registry: QRStationRegistry,
        detector: QRDetector,
        audio_player: LocalAudioPlayer,
        motion: QRMotionDriver,
        llm: ConversationManagerLLMAdapter,
        pre_stop_delay_s: float = 5.0,
        cooldown_s: float = 10.0,
        max_turn_duration_s: float = 8.0,
        prevent_repeated_qr: bool = True,
        scan_sleep_s: float = 0.05,
    ) -> None:
        self.registry = registry
        self.detector = detector
        self.audio_player = audio_player
        self.motion = motion
        self.llm = llm
        self.pre_stop_delay_s = pre_stop_delay_s
        self.cooldown_s = cooldown_s
        self.max_turn_duration_s = max_turn_duration_s
        self.prevent_repeated_qr = prevent_repeated_qr
        self.scan_sleep_s = scan_sleep_s
        self.state = OttoQRState.STARTUP
        self.completed_qr_values: set[str] = set()
        self.stop_requested = asyncio.Event()
        self.events: list[dict[str, Any]] = []

    async def run(self) -> list[dict[str, Any]]:
        """
        @TASK: Ejecutar recorrido reactivo QR.
        @OUTPUT: Lista de eventos para auditoría; finaliza con QR final, stop manual o cancelación.
        """
        await self.motion.start_loop()

        try:
            await self._run_startup()

            self.detector.start()
            self.state = OttoQRState.SCANNING
            await self.motion.drive_forward()
            self._record("scan_started", "Escáner QR activo; marcha normal iniciada.")

            while not self.stop_requested.is_set():
                if self.state != OttoQRState.SCANNING:
                    await asyncio.sleep(0)
                    continue

                # @PERFORMANCE: OpenCV puede bloquear; se aísla en thread para no frenar comandos move().
                detection = await asyncio.to_thread(self.detector.read_once)

                if detection is None:
                    await asyncio.sleep(self.scan_sleep_s)
                    continue

                station = self.registry.resolve(detection.value)

                if station is None:
                    self._record("qr_unknown_ignored", "QR desconocido ignorado.", qr_value=detection.value)
                    await asyncio.sleep(self.scan_sleep_s)
                    continue

                if self.prevent_repeated_qr and station.qr_value in self.completed_qr_values:
                    self._record("qr_repeated_ignored", "QR ya ejecutado ignorado.", qr_value=station.qr_value)
                    await asyncio.sleep(self.scan_sleep_s)
                    continue

                await self._handle_station(station)

                if station.is_final:
                    break

            return self.events

        except asyncio.CancelledError:
            self._record("cancelled", "FSM QR cancelada por el orquestador.")
            raise

        except Exception as exc:
            self.state = OttoQRState.EMERGENCY
            self._record("emergency", f"Error crítico en FSM QR: {exc}")
            LOGGER.exception("[QR_FSM] Error crítico: %s", exc)
            await self.motion.stop_motion()
            raise

        finally:
            self.detector.stop()
            await self.motion.stop_loop()
            self.state = OttoQRState.STOPPED
            self._record("stopped", "FSM QR detenida.")

    async def stop(self) -> None:
        """@TASK: Solicitar stop ordenado desde fuera de la FSM."""
        self.stop_requested.set()
        await self.motion.stop_motion()

    async def _run_startup(self) -> None:
        """@TASK: Ejecutar audio de bienvenida sin buscar QR."""
        start = self.registry.start
        self.state = OttoQRState.STARTUP
        self._record("startup", "Ejecutando bienvenida inicial.", station_id=start.id)

        await self.motion.stop_motion()
        await self.motion.turn_degrees(start.turn_to_students_deg, max_duration_s=self.max_turn_duration_s)
        await self.audio_player.play(start.audio_path)
        await self.motion.turn_degrees(start.turn_to_front_deg, max_duration_s=self.max_turn_duration_s)

    async def _handle_station(self, station: QRStation) -> None:
        """@TASK: Ejecutar reacción completa ante un QR conocido."""
        self._record("qr_detected", "QR conocido detectado.", qr_value=station.qr_value, station_id=station.id)

        # STEP 1: Avance suave 5 s sin bloquear el loop de movimiento.
        self.state = OttoQRState.APPROACH_DELAY
        await self.motion.drive_approach()
        await asyncio.sleep(self.pre_stop_delay_s)

        # STEP 2: Detenerse y girar hacia estudiantes.
        self.state = OttoQRState.STOPPED_FOR_STATION
        await self.motion.stop_motion()

        self.state = OttoQRState.TURN_TO_STUDENTS
        await self.motion.turn_degrees(station.turn_to_students_deg, max_duration_s=self.max_turn_duration_s)

        # STEP 3: Reproducir exactamente el audio asociado al QR leído.
        self.state = OttoQRState.PLAYING_AUDIO
        await self.audio_player.play(station.audio_path)
        self.completed_qr_values.add(station.qr_value)
        self._record("audio_played", "Audio local reproducido.", qr_value=station.qr_value, audio_path=station.audio_path)

        # STEP 4: QR final: no reanudar marcha; activar LLM local.
        if station.is_final:
            self.state = OttoQRState.FINAL_LLM
            await self.llm.start_session(zone_id=station.llm_zone_id or station.id)
            self._record("final_llm", "LLM local activado en estación final.", qr_value=station.qr_value)
            self.stop_requested.set()
            return

        # STEP 5: Volver al frente, caminar y enfriar cámara 10 s.
        self.state = OttoQRState.TURN_TO_FRONT
        await self.motion.turn_degrees(station.turn_to_front_deg, max_duration_s=self.max_turn_duration_s)

        await self.motion.drive_forward()
        self.state = OttoQRState.COOLDOWN
        self._record("cooldown_started", "Cooldown QR iniciado; cámara ignorada.", seconds=self.cooldown_s)
        await asyncio.sleep(self.cooldown_s)

        self.state = OttoQRState.SCANNING
        self._record("scan_resumed", "Escaneo QR reactivado.")

    def _record(self, event: str, detail: str, **extra: Any) -> None:
        payload = {"state": self.state.value, "event": event, "detail": detail, **extra}
        self.events.append(payload)
        LOGGER.info("[QR_FSM] %s | %s | %s", self.state.value, event, detail)