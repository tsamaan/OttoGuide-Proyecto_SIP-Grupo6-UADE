# OttoGuide MVP — Robot Guía Universitario Autónomo

- `Estado: RC1_LOCKED`
- `Modo: Air-gapped / HIL-ready`
- `Hardware: Unitree G1 EDU 8`
- `Validación física: baseline L0/L1 capturado (2026-06-23); mapa/odom/TF/Nav2 pendientes`

## Resumen Ejecutivo

`OttoGuide` es un MVP de robot guía universitario autónomo para visitas en `UADE`, orientado a navegación guiada, interacción local, operación sin dependencia de cloud y observabilidad durante validación `HIL`.

El sistema está congelado funcionalmente bajo `RC1_LOCKED`. La arquitectura, documentación y empaquetado local fueron preparados para validación, pero la operación física completa sobre el `Unitree G1 EDU 8` sigue pendiente.

## Ficha Técnica Rápida

| Área | Valor |
|---|---|
| Robot | `Unitree G1 EDU 8` |
| Companion PC | `192.168.123.164` |
| Locomoción / DDS | `192.168.123.161` |
| LiDAR | `Livox MID360`, default SDK2 `192.168.123.120`; `.20` queda como alternativa `PENDING_HIL` |
| Cámara | `Intel RealSense D435i` |
| Runtime HIL | `ROS 2 Foxy` |
| Control primario | `SDK2/DDS Unicast` |
| IA local | `Ollama` |
| Backend | `FastAPI + asyncio` |

## Arquitectura High-Level

- `FastAPI`: API local, dashboard operativo y exposición de estado.
- `TourOrchestrator`: FSM de misión y coordinación de alto nivel.
- `OttoEventBus`: distribución interna de eventos entre módulos.
- `Nav2Bridge`: frontera controlada entre OttoGuide y `ROS 2/Nav2`.
- `Unitree SDK2 Adapter`: integración de control directo vía `DDS`.
- `ConversationManager`: interacción local `STT/LLM/TTS`.
- `CycloneDDS`: transporte `DDS` unicast para operación HIL.

## Unitree Go / Unitree Explore

`Unitree Go` se conserva solo como referencia pasiva y de diagnóstico del plano factory `192.168.12.x`. No es ruta primaria de control del `G1 EDU`.

`Unitree Explore` es la app oficial para `G1/G1_D`, pero queda fuera de la ruta MVP operativa por `AR8030`, autenticación enterprise, dependencia cloud y protocolo binario.

La ruta primaria operativa de OttoGuide es `SDK2/DDS Unicast` hacia `192.168.123.161`.

## Mapa del Repositorio

```text
.
├── README.md
├── TODO.md
├── codigo ottoguide/      ← software, runtime y tests
│   ├── src/
│   ├── scripts/
│   ├── tools/
│   ├── config/
│   ├── launch/
│   ├── ros2_ws/
│   └── libs/
└── docs/                  ← documentación, planificación, operaciones y auditorías
    ├── README.md
    ├── Arquitectura/
    ├── Operaciones_HIL/
    ├── Hardware_Reference/
    ├── AppPhone/
    ├── Auditorias/
    ├── Historico/
    ├── Investigacion/
    ├── planning/
    └── audits/
```

- `README.md`: front-page pública y mapa de navegación del repositorio.
- `TODO.md`: backlog post-`RC1` y validaciones HIL pendientes.
- `codigo ottoguide/`: todo el software, runtime, scripts, herramientas, configuración y tests.
- `docs/`: única raíz documental — arquitectura, operaciones HIL, referencias de hardware, planificación, auditorías e histórico.

La raíz del repositorio se mantiene limpia. No recrear `documentacion general del proyecto/` ni `planificacion/` como raíces independientes.

## Roadmap de Ejecución Rápida

Los procedimientos operativos viven en runbooks dedicados. Este `README.md` no duplica pasos de despliegue ni pruebas:

- [Startup RC1](<docs/Operaciones_HIL/RUNBOOK_STARTUP_RC1.md>)
- [Deploy](<docs/Operaciones_HIL/RUNBOOK_DEPLOY.md>)
- [Protocolo HIL](<docs/Operaciones_HIL/HIL_TESTING_PROTOCOL.md>)
- [Livox SDK2 bridge](<docs/Operaciones_HIL/RUNBOOK_LIVOX_SDK2_BRIDGE.md>)
- [OttoGuide map quickstart](<docs/Operaciones_HIL/OTTOGUIDE_MAP_EXECUTABLE_QUICKSTART.md>)
- [ODOM/TF offline analysis](<docs/Operaciones_HIL/ODOM_TF_OFFLINE_ANALYSIS_20260618.md>)
- [ODOM bridge contract](<docs/Arquitectura/ODOM_BRIDGE_CONTRACT.md>)
- [Preflight ODOM/TF](<docs/Operaciones_HIL/PREFLIGHT_PROXIMA_SESION_FISICA_ODOM_TF.md>)
- [Demo local](<docs/Operaciones_HIL/RUNBOOK_DEMO_LOCAL.md>)
- [Packet capture HIL](<docs/Operaciones_HIL/RUNBOOK_PACKET_CAPTURE_HIL.md>)

## Estado Actual

Hecho:

- Arquitectura `RC1` congelada.
- Documentación saneada y reorganizada.
- `CycloneDDS` XML corregido.
- `Unitree Go` / `Unitree Explore` segregado documentalmente.
- `TODO.md` convertido en backlog post-`RC1`.
- `codigo ottoguide/libs/` documentado como vendorización air-gapped intencional.

Validación física (baseline 2026-06-23, HEAD físico `23d9d9c`):

- `/utlidar/cloud`, `/livox/imu`, `/scan`: **PASS físico parcial** — observados y grabados en toma de ruta.
- Telemetría Unitree (`/unitree/*`): **PASS físico** — bridge nativo construido, iniciado y validado.
- `/odom`, `/tf`, `/tf_static`: **pendiente** — no presentes en sesión de auditoría.
- `/map`, `Nav2`, `SLAM`, `controller_server`: **pendiente** — no presentes.
- Movimiento por software: **ninguno ejecutado**.
- Código `80417b7` (actual publicado): **no desplegado físicamente**.

Pendiente:

- Desplegar `80417b7` en el robot y ejecutar P0 v2 formal.
- Confirmar IP efectiva del `Livox MID360` (`.120` vs `.20`).
- Habilitar odometría y TF en siguiente sesión física.
- Confirmar generación de `/map` con SLAM.
- Validación de `Audio SDK2`.
- Pruebas físicas de seguridad.

## Seguridad Operativa

- No ejecutar comandos de movimiento sin operador físico presente.
- No usar `/cmd_vel` desde Python OttoGuide.
- No usar `/rest/remote/packet/*` como ruta de control.
- Mantener `L1 + A` / `Damp` como seguridad física según procedimientos.
- Seguir los runbooks HIL antes de cualquier ejecución sobre hardware.

## Enlaces Principales

| Recurso | Ruta |
|---|---|
| Documentación técnica | [docs/README.md](<docs/README.md>) |
| Unificación de ramas y handoff operativo | [UNIFICACION_RAMAS_Y_HANDOFF.md](<docs/Arquitectura/UNIFICACION_RAMAS_Y_HANDOFF.md>) |
| Backlog | [TODO.md](<TODO.md>) |
| Arquitectura operativa | [ARQUITECTURA_OPERATIVA_RC1.md](<docs/Arquitectura/ARQUITECTURA_OPERATIVA_RC1.md>) |
| `ROS 2` / `DDS` | [ROS2_INTEGRATION.md](<docs/Arquitectura/ROS2_INTEGRATION.md>) |
| Contrato ODOM bridge | [ODOM_BRIDGE_CONTRACT.md](<docs/Arquitectura/ODOM_BRIDGE_CONTRACT.md>) |
| Protocolo HIL | [HIL_TESTING_PROTOCOL.md](<docs/Operaciones_HIL/HIL_TESTING_PROTOCOL.md>) |
| Preflight sensores | [PREFLIGHT_CERTIFICACION_SENSORES_PENDING.md](<docs/Operaciones_HIL/PREFLIGHT_CERTIFICACION_SENSORES_PENDING.md>) |
| Preflight ODOM/TF | [PREFLIGHT_PROXIMA_SESION_FISICA_ODOM_TF.md](<docs/Operaciones_HIL/PREFLIGHT_PROXIMA_SESION_FISICA_ODOM_TF.md>) |
| ODOM/TF offline | [ODOM_TF_OFFLINE_ANALYSIS_20260618.md](<docs/Operaciones_HIL/ODOM_TF_OFFLINE_ANALYSIS_20260618.md>) |
| Quickstart de mapeo | [OTTOGUIDE_MAP_EXECUTABLE_QUICKSTART.md](<docs/Operaciones_HIL/OTTOGUIDE_MAP_EXECUTABLE_QUICKSTART.md>) |
| Auditorias HIL | [Auditorias](<docs/Auditorias/>) |
| AppPhone / APK | [README_AppPhone.md](<docs/AppPhone/README_AppPhone.md>) |

Nota de continuidad: la rama activa de integración es `review/orchestrator-unification`; `main` no es la base de continuidad.
