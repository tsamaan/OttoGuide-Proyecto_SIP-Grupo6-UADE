"""
@TASK: Decodificar y estabilizar valores QR a partir de frames ya capturados (U2)
@INPUT: Frames BGR ya leidos por VisionProcessor; nunca abre una camara propia
@OUTPUT: QRFrameDecoder (Protocol), OpenCVQRCodeDecoder, StableQRFrameDetector
@CONTEXT: U2 — Integracion del sensor QR de estaciones. La camara es propiedad
          exclusiva de VisionProcessor; este modulo solo decodifica frames que ya
          fueron leidos por el unico VideoCapture existente. No crea VideoCapture,
          no abre ni libera camara, no usa threads ni I/O propio.
@SECURITY: cv2 se importa de forma lazy (solo al construir OpenCVQRCodeDecoder o en
           su primera decodificacion) para que este modulo siga siendo importable
           sin OpenCV instalado. No retiene frames entre llamadas.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class QRDecodeError(Exception):
    """Error tipado de decodificacion QR; nunca propaga excepciones nativas de cv2."""


@runtime_checkable
class QRFrameDecoder(Protocol):
    def decode(self, frame: object) -> str | None:
        ...


class OpenCVQRCodeDecoder:
    """
    @TASK: Decodificar un valor QR de un frame ya capturado usando cv2.QRCodeDetector
    @CONTEXT: No abre camara; opera exclusivamente sobre el frame recibido por parametro.
    """

    def __init__(self) -> None:
        self._cv2_detector = None

    def _ensure_detector(self):
        if self._cv2_detector is None:
            import cv2  # lazy: este modulo debe ser importable sin OpenCV instalado

            self._cv2_detector = cv2.QRCodeDetector()
        return self._cv2_detector

    def decode(self, frame: object) -> str | None:
        detector = self._ensure_detector()
        try:
            value, _points, _straight = detector.detectAndDecode(frame)
        except Exception as exc:
            raise QRDecodeError(f"qr_decode_failed:{type(exc).__name__}") from exc

        normalized = (value or "").strip()
        return normalized or None


@dataclass(frozen=True, slots=True)
class StableQRValue:
    value: str
    confidence_or_stability: float


class StableQRFrameDetector:
    """
    @TASK: Filtrar lecturas QR ruidosas y emitir exactamente una vez por presencia continua
    @CONTEXT: Pura maquina de estados sincrona; sin reloj, sin threads, sin I/O.
              Procesa un frame por llamada; el caller controla el cadenciado.
    """

    def __init__(
        self,
        decoder: QRFrameDecoder,
        stable_frames: int = 4,
        release_frames: int = 3,
    ) -> None:
        if stable_frames <= 0:
            raise ValueError("stable_frames must be greater than 0")
        if release_frames <= 0:
            raise ValueError("release_frames must be greater than 0")

        self._decoder = decoder
        self._stable_frames = stable_frames
        self._release_frames = release_frames

        self._candidate_value: str | None = None
        self._candidate_count: int = 0
        self._absence_count: int = 0
        self._emitted_for_current_presence: bool = False

    def process_frame(self, frame: object) -> StableQRValue | None:
        raw_value = self._decoder.decode(frame)
        normalized = (raw_value or "").strip() or None

        if normalized is None:
            self._absence_count += 1
            if self._absence_count >= self._release_frames:
                self.reset()
            return None

        self._absence_count = 0

        if normalized != self._candidate_value:
            self._candidate_value = normalized
            self._candidate_count = 1
            self._emitted_for_current_presence = False
        else:
            self._candidate_count += 1

        if (
            self._candidate_count >= self._stable_frames
            and not self._emitted_for_current_presence
        ):
            self._emitted_for_current_presence = True
            return StableQRValue(value=normalized, confidence_or_stability=1.0)

        return None

    def reset(self) -> None:
        self._candidate_value = None
        self._candidate_count = 0
        self._absence_count = 0
        self._emitted_for_current_presence = False


__all__ = [
    "OpenCVQRCodeDecoder",
    "QRDecodeError",
    "QRFrameDecoder",
    "StableQRFrameDetector",
    "StableQRValue",
]
