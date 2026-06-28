from __future__ import annotations

from importlib import import_module
from typing import Any

_SYMBOL_MODULE_MAP: dict[str, str] = {
    "CameraModel": ".vision_processor",
    "OdometryVector": ".vision_processor",
    "PoseEstimate": ".vision_processor",
    "VisionProcessor": ".vision_processor",
    # Contrato canonico del sensor de estaciones por QR (U1)
    "QRStationDetected": ".station_trigger",
    "StationTriggerHealth": ".station_trigger",
    "StationTriggerPort": ".station_trigger",
    "StationTriggerState": ".station_trigger",
    # Decodificacion y estabilidad QR sobre frames compartidos (U2)
    "OpenCVQRCodeDecoder": ".qr_frame_detector",
    "QRDecodeError": ".qr_frame_detector",
    "QRFrameDecoder": ".qr_frame_detector",
    "StableQRFrameDetector": ".qr_frame_detector",
    "StableQRValue": ".qr_frame_detector",
    # Adaptador StationTriggerPort sobre la camara compartida de VisionProcessor (U2)
    "StationTriggerUnavailableError": ".vision_station_trigger",
    "VisionStationTrigger": ".vision_station_trigger",
}


def __getattr__(name: str) -> Any:
    module_name = _SYMBOL_MODULE_MAP.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name, package=__name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals().keys()) | set(__all__))


__all__ = [
    "CameraModel",
    "OdometryVector",
    "PoseEstimate",
    "VisionProcessor",
    "QRStationDetected",
    "StationTriggerHealth",
    "StationTriggerPort",
    "StationTriggerState",
    "OpenCVQRCodeDecoder",
    "QRDecodeError",
    "QRFrameDecoder",
    "StableQRFrameDetector",
    "StableQRValue",
    "StationTriggerUnavailableError",
    "VisionStationTrigger",
]
