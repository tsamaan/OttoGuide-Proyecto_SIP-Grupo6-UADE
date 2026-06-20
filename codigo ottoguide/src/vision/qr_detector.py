from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import cv2


@dataclass(frozen=True, slots=True)
class QRDetection:
    """
    @TASK: Representar una lectura QR estable.
    @OUTPUT: Texto QR y timestamp monotónico de detección.
    """

    value: str
    timestamp_s: float


class QRDetector:
    """
    @TASK: Detectar códigos QR desde cámara usando OpenCV.
    @CONTEXT: No conoce estaciones, audios, LLM ni movimiento; solo devuelve texto QR estable.
    """

    def __init__(self, *, camera_index: int = 0, stable_frames: int = 4) -> None:
        if stable_frames <= 0:
            raise ValueError("stable_frames debe ser mayor a 0.")

        self._camera_index = camera_index
        self._stable_frames = stable_frames
        self._detector = cv2.QRCodeDetector()
        self._cap: Optional[cv2.VideoCapture] = None
        self._last_value = ""
        self._same_value_count = 0

    def start(self) -> None:
        """
        @TASK: Abrir cámara para una sesión de escaneo.
        @OUTPUT: VideoCapture activo o RuntimeError controlado.
        """
        if self._cap is not None:
            return

        cap = cv2.VideoCapture(self._camera_index)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"No se pudo abrir la cámara QR index={self._camera_index}.")

        self._cap = cap
        self._last_value = ""
        self._same_value_count = 0

    def stop(self) -> None:
        """
        @TASK: Liberar cámara y limpiar buffer de estabilidad.
        """
        if self._cap is not None:
            self._cap.release()

        self._cap = None
        self._last_value = ""
        self._same_value_count = 0

    def read_once(self) -> Optional[QRDetection]:
        """
        @TASK: Leer un frame y devolver QR solo si se repite en stable_frames consecutivos.
        @OUTPUT: QRDetection o None si no hay lectura estable.
        """
        if self._cap is None:
            raise RuntimeError("QRDetector no iniciado. Llamar start().")

        ok, frame = self._cap.read()
        if not ok or frame is None:
            return None

        value, _points, _straight = self._detector.detectAndDecode(frame)
        value = (value or "").strip()

        if not value:
            self._last_value = ""
            self._same_value_count = 0
            return None

        if value == self._last_value:
            self._same_value_count += 1
        else:
            self._last_value = value
            self._same_value_count = 1

        if self._same_value_count < self._stable_frames:
            return None

        return QRDetection(value=value, timestamp_s=time.monotonic())