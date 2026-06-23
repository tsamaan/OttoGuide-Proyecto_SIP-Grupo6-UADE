"""Endpoints de control: los tres botones de la web."""
from fastapi import APIRouter

from app.services import process_manager
from app.services.robot_state import state

router = APIRouter(tags=["control"])


@router.post("/tour/start")
def tour_start():
    """Boton 'Iniciar recorrido': arranca el orquestador completo (movimiento + recorrido)."""
    return process_manager.start_tour()


@router.post("/chat/start")
def chat_start():
    """Boton 'Iniciar charla': arranca solo el pipeline de conversacion (IA)."""
    return process_manager.start_chat()


@router.post("/emergency")
def emergency_stop():
    """Boton 'Terminar ejecucion': frena lo que este corriendo."""
    return process_manager.stop_all()


@router.get("/status")
def status():
    """Estado actual del sistema, para que la web sepa que esta corriendo."""
    return state.snapshot()
