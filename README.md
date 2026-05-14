# OttoGuide MVP — Robot Guía Universitario Autónomo

- `Estado: RC1_LOCKED`
- `Modo: Air-gapped / HIL-ready`
- `Hardware: Unitree G1 EDU 8`
- `Validación física: pendiente`

## Resumen Ejecutivo

`OttoGuide` es un MVP de robot guía universitario autónomo para visitas en `UADE`, orientado a navegación guiada, interacción local, operación sin dependencia de cloud y observabilidad durante validación `HIL`.

El sistema está congelado funcionalmente bajo `RC1_LOCKED`. La arquitectura, documentación y empaquetado local fueron preparados para validación, pero la operación física completa sobre el `Unitree G1 EDU 8` sigue pendiente.

## Ficha Técnica Rápida

| Área | Valor |
|---|---|
| Robot | `Unitree G1 EDU 8` |
| Companion PC | `192.168.123.164` |
| Locomoción / DDS | `192.168.123.161` |
| LiDAR | `Livox MID360`, IP pendiente entre `192.168.123.20` y `192.168.123.120` |
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
├── codigo ottoguide/
│   ├── src/
│   ├── scripts/
│   ├── config/
│   └── libs/
└── documentacion general del proyecto/
    ├── README.md
    ├── Arquitectura/
    ├── Operaciones_HIL/
    ├── Hardware_Reference/
    ├── AppPhone/
    ├── Auditorias/
    └── Historico/
```

- `README.md`: front-page pública y mapa de navegación del repositorio.
- `TODO.md`: backlog post-`RC1` y validaciones HIL pendientes.
- `codigo ottoguide/src/`: lógica de aplicación y módulos runtime.
- `codigo ottoguide/scripts/`: orquestadores y utilidades HIL.
- `codigo ottoguide/config/`: configuración operativa.
- `codigo ottoguide/libs/`: dependencias vendorizadas air-gapped preservadas.
- `documentacion general del proyecto/`: documentación técnica profunda e histórica.

## Roadmap de Ejecución Rápida

Los procedimientos operativos viven en runbooks dedicados. Este `README.md` no duplica pasos de despliegue ni pruebas:

- [Startup RC1](<documentacion general del proyecto/Operaciones_HIL/RUNBOOK_STARTUP_RC1.md>)
- [Deploy](<documentacion general del proyecto/Operaciones_HIL/RUNBOOK_DEPLOY.md>)
- [Protocolo HIL](<documentacion general del proyecto/Operaciones_HIL/HIL_TESTING_PROTOCOL.md>)
- [Demo local](<documentacion general del proyecto/Operaciones_HIL/RUNBOOK_DEMO_LOCAL.md>)
- [Packet capture HIL](<documentacion general del proyecto/Operaciones_HIL/RUNBOOK_PACKET_CAPTURE_HIL.md>)

## Estado Actual

Hecho:

- Arquitectura `RC1` congelada.
- Documentación saneada y reorganizada.
- `CycloneDDS` XML corregido.
- `Unitree Go` / `Unitree Explore` segregado documentalmente.
- `TODO.md` convertido en backlog post-`RC1`.
- `codigo ottoguide/libs/` documentado como vendorización air-gapped intencional.

Pendiente:

- Validación HIL real sobre el robot físico.
- Confirmar IP efectiva del `Livox MID360`.
- Confirmar disponibilidad de `/utlidar/cloud`.
- Confirmar disponibilidad de `/scan`.
- Confirmar generación de `/map`.
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
| Documentación técnica | [documentacion general del proyecto/README.md](<documentacion general del proyecto/README.md>) |
| Backlog | [TODO.md](<TODO.md>) |
| Arquitectura operativa | [ARQUITECTURA_OPERATIVA_RC1.md](<documentacion general del proyecto/Arquitectura/ARQUITECTURA_OPERATIVA_RC1.md>) |
| `ROS 2` / `DDS` | [ROS2_INTEGRATION.md](<documentacion general del proyecto/Arquitectura/ROS2_INTEGRATION.md>) |
| Protocolo HIL | [HIL_TESTING_PROTOCOL.md](<documentacion general del proyecto/Operaciones_HIL/HIL_TESTING_PROTOCOL.md>) |
| Preflight sensores | [PREFLIGHT_CERTIFICACION_SENSORES_PENDING.md](<documentacion general del proyecto/Operaciones_HIL/PREFLIGHT_CERTIFICACION_SENSORES_PENDING.md>) |
| AppPhone / APK | [README_AppPhone.md](<documentacion general del proyecto/AppPhone/README_AppPhone.md>) |
