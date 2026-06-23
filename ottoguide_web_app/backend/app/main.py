"""
Backend de OttoGuide (FastAPI). Corre en el robot, puerto 3000.
Expone el control de los procesos (recorrido / charla / stop) y la telemetria.
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import control, telemetry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = FastAPI(title="OttoGuide Backend", version="0.1.0")

# CORS: la web corre en otra maquina (notebook, puerto 3001) y le pega por RJ45.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(control.router)
app.include_router(telemetry.router)


@app.get("/")
def root():
    return {
        "service": "ottoguide-backend",
        "status": "ok",
        "mock_mode": settings.MOCK_MODE,
    }


@app.get("/health")
def health():
    return {"status": "ok"}
