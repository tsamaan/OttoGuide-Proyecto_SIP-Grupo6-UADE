# Límite arquitectónico: HIL Read-Only Observability Tool

## 1. Qué es

`codigo ottoguide/tools/hil/readonly_observability/` es una **herramienta de
observabilidad física read-only para HIL** (Hardware-In-the-Loop), no un
componente del producto. Permite abrir un dashboard Web con telemetría real
del Unitree G1 (motores, IMU, odometría, LiDAR, BMS) sin ninguna autoridad de
movimiento ni de interacción.

```text
R0B1_ROLE = HIL_READ_ONLY_OBSERVABILITY_TOOL
CANONICAL_PRODUCT_BACKEND = unchanged
SECOND_PRODUCT_FASTAPI_AUTHORITY = prohibited
```

## 2. Relación con los invariantes arquitectónicos del proyecto

`AGENTS.md` y `docs/Arquitectura/UNIFICACION_RAMAS_Y_HANDOFF.md` declaran:

```text
ONE_FASTAPI = YES
ONE_TOUR_ORCHESTRATOR = YES
ONE_MOTION_AUTHORITY = YES
WORKER_MOTION_AUTHORITY = PROHIBITED
```

El bridge FastAPI de esta herramienta (`companion/ottoguide_readonly_bridge.py`)
**no es** el FastAPI canónico del producto. Es un segundo proceso HTTP,
explícitamente fuera del alcance de `ONE_FASTAPI`, cuyo único propósito es
servir telemetría DDS de solo lectura a un dashboard de diagnóstico. Nunca
debe integrarse, montarse ni componerse con el backend canónico del producto,
ni sustituirlo, ni ejecutarse simultáneamente como si fuera parte de él.

## 3. Qué garantiza el runtime del Companion

Validado mediante `companion/static_gate.py` (análisis AST/imports/calls) y
observado en ejecución física (sesión `r0b1-20260717T215047Z`,
ver `docs/Operaciones_HIL/Evidencia/WEB_R0B1_REAL_20260717/`):

```text
DataReader only (DataWriter = 0)
Movement clients imported = 0 (LocoClient, SportClient, MotionSwitcher, AudioClient)
Movement commands sent = 0
HTTP mutations (POST/PUT/PATCH/DELETE) -> 405 READ_ONLY_DEMO
bind = 127.0.0.1 (loopback only)
```

## 4. Qué NO hace esta herramienta

- No orquesta el tour ni ninguna misión.
- No controla movimiento (`Move`, `StopMove`, `Damp`, postura, `/cmd_vel`).
- No participa en navegación (Nav2, `/odom` como fuente de control, TF).
- No reemplaza ni compite con `codigo ottoguide/main.py`,
  `codigo ottoguide/src/core/tour_orchestrator.py`,
  `codigo ottoguide/src/interaction/**` ni `codigo ottoguide/src/navigation/**`
  — ninguno de esos archivos fue modificado por este checkpoint.
- No es una fuente autoritativa de validación de `/odom`, TF, Nav2 ni
  navegación autónoma (ver `PHYSICAL_VALIDATION_LIMITATIONS.md`).

## 5. Dónde vive y cómo se despliega

- **Companion (robot)**: 9 archivos Python/bash bajo `companion/`, ejecutados
  con un intérprete descubierto dinámicamente
  (`companion/discover_companion_python.sh`) — nunca un path de venv fijo.
- **Notebook**: scripts PowerShell portátiles bajo `notebook/`, que usan
  `%USERPROFILE%` y una raíz SSH configurable (`C:\OG\OttoGuide-SSH` por
  defecto), nunca un nombre de equipo o usuario fijo.
- **Frontend**: React/Vite bajo `frontend/`, con un build REAL precompilado en
  `frontend/dist/` para que una Notebook sin Node pueda servirlo con
  `python -m http.server`.
- **Replay offline**: `replay/ottoguide_replay_server.py`, sin dependencias de
  terceros, para validar la interfaz sin robot ni SSH.

## 6. Evolución futura

Cualquier intento de convertir este bridge en backend canónico, de darle
autoridad de movimiento, o de fusionarlo con el orquestador del producto,
requiere una decisión de arquitectura explícita y revisión humana (ver
sección "Cambios de arquitectura" en `AGENTS.md`) — no se autoriza
implícitamente por la existencia de este checkpoint.
