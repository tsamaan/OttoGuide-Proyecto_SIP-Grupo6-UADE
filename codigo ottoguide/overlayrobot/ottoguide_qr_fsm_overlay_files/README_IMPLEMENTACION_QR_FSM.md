# Implementación QR FSM reactiva — OttoGuide

Este paquete está armado para copiarse encima del ZIP original `OttoGuide-Proyecto_SIP-Grupo6-UADE-robot.zip`.

## Archivos agregados

Dentro de `OttoGuide-Proyecto_SIP-Grupo6-UADE-robot/codigo ottoguide/`:

- `config/qr_stations.yaml`
- `audio/README.md`
- `src/vision/qr_detector.py`
- `src/core/local_audio_player.py`
- `src/core/qr_motion_driver.py`
- `src/core/otto_qr_fsm.py`

## Archivos modificados

- `config/settings.py`
- `src/vision/__init__.py`
- `src/core/__init__.py`
- `src/core/tour_orchestrator.py`
- `api/schemas.py`
- `api/router.py`

## Endpoint nuevo

```bash
curl -X POST http://localhost:8000/tour/start-qr-fsm \
  -H "Content-Type: application/json" \
  -d '{"tour_id": "uade-qr-fsm-001"}'
```

## Audios requeridos

Colocar estos archivos reales en `codigo ottoguide/audio/`:

- `I_bienvenida.wav`
- `P01_molinetes.wav`
- `P02_hall_central.wav`
- `P03_pasillo_lima2.wav`
- `F_cierre.wav`

## QRs válidos

- `QR_MOLINETES`
- `QR_HALL_CENTRAL`
- `QR_PASILLO_LIMA2`
- `QR_OFICINAS_GESTION`

## Validación

Desde `codigo ottoguide/`:

```bash
python -m compileall -q config src api main.py
aplay audio/P01_molinetes.wav
ROBOT_MODE=mock python main.py
```

