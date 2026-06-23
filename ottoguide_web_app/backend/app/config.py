"""Configuracion del backend leida de variables de entorno."""
import os


def _as_bool(value: str) -> bool:
    return str(value).lower() in ("1", "true", "yes", "on")


class Settings:
    PORT = int(os.getenv("PORT", "3000"))
    MOCK_MODE = _as_bool(os.getenv("MOCK_MODE", "true"))
    # Origenes permitidos para CORS. "*" para una herramienta de LAN. Separar con comas.
    CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]

    # --- Datos para la integracion REAL con el robot (ajustar cuando se confirmen) ---
    # Carpeta del repo de movimiento en el robot, donde vive ./tools/hil/ottoguide-map
    ROBOT_REPO_DIR = os.getenv(
        "ROBOT_REPO_DIR",
        "/home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE/codigo ottoguide",
    )
    # Binario del pipeline conversacional (pilar IA) en la Jetson
    OTTO_PIPELINE_BIN = os.getenv("OTTO_PIPELINE_BIN", "otto_pipeline")

    # Interfaz de red para la suscripcion DDS al lowstate del robot.
    # TODO: confirmar con `ip addr` en el robot (subred 192.168.123.x).
    #       Puede llamarse eth0, enp3s0, enpXsY, etc.
    DDS_INTERFACE = os.getenv("DDS_INTERFACE", "eth0")

    # Timeout en segundos: si el lector DDS no recibe ningun frame en este
    # tiempo, get_frame() cae al mock para no dejar la UI sin datos.
    DDS_TIMEOUT_S = float(os.getenv("DDS_TIMEOUT_S", "5"))


settings = Settings()
