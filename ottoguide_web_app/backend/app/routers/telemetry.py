"""Telemetria del robot: WebSocket en tiempo real + GET de respaldo (polling)."""
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.telemetry_source import get_frame

router = APIRouter(tags=["telemetry"])

# 10 Hz, igual que el limitador del lector original.
INTERVAL_S = 0.1


@router.get("/telemetry")
def telemetry_once():
    """Devuelve un frame puntual. Sirve de fallback si el WebSocket no esta disponible."""
    return get_frame()


@router.websocket("/telemetry")
async def telemetry_ws(ws: WebSocket):
    """Envia un frame de telemetria cada 100 ms mientras el cliente este conectado."""
    await ws.accept()
    try:
        while True:
            await ws.send_json(get_frame())
            await asyncio.sleep(INTERVAL_S)
    except WebSocketDisconnect:
        pass
    except Exception:
        # cualquier otro corte de conexion: cerramos silenciosamente
        pass
