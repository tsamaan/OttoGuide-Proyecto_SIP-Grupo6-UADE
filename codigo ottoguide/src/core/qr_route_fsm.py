"""Compatibilidad con la nueva FSM QR overlay.

Este módulo queda como shim para importadores legados; la implementación
real vive en [src/core/otto_qr_fsm.py](src/core/otto_qr_fsm.py).
"""

from __future__ import annotations

from .otto_qr_fsm import ConversationManagerLLMAdapter, OttoQRAsyncFSM, OttoQRState, QRStationRegistry

QRGuidedRouteController = OttoQRAsyncFSM

__all__ = [
    "ConversationManagerLLMAdapter",
    "OttoQRAsyncFSM",
    "OttoQRState",
    "QRGuidedRouteController",
    "QRStationRegistry",
]