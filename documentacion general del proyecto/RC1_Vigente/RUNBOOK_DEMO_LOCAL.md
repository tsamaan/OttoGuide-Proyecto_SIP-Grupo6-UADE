# @TASK: Ejecutar demostracion local Offline/Mock del pipeline de interaccion OttoGuide.
# @INPUT: PC de desarrollo con Python, .venv del proyecto, Ollama local y hardware de audio disponible.
# @OUTPUT: Backend FastAPI y dashboard WS operativos en localhost sin conexion al robot fisico.
# @CONTEXT: Runbook de demostracion local RC1_LOCKED sin alterar locomocion real.
# @SECURITY: ROBOT_MODE=mock y NAV_BRIDGE_ACTIVE=false obligatorios para evitar llamadas DDS/SDK.

## STEP 1: Prerrequisitos del host local

- Ollama activo en el host local (`http://127.0.0.1:11434`).
- Modelo local descargado (ejemplo: `qwen2.5:3b`).
- Dispositivo de audio del host con captura y reproduccion habilitadas.
- Entorno virtual creado en `codigo ottoguide/.venv`.

## STEP 2: Arranque de demo local

```bash
cd "codigo ottoguide"
bash scripts/demo_interaction_local.sh
```

## STEP 3: Verificacion de backend y dashboard

- API local: `http://127.0.0.1:8000/status`
- Dashboard: `http://127.0.0.1:8000/dashboard`
- WebSocket de telemetria: `ws://127.0.0.1:8000/ws/telemetry`

## STEP 4: Cierre controlado

- Presionar `Ctrl+C` en la terminal donde corre `demo_interaction_local.sh`.
- El `trap` del script finaliza uvicorn y cierra la sesion de demo.
