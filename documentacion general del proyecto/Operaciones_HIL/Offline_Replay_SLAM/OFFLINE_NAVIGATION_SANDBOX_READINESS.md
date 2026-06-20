# Offline Navigation Sandbox — Readiness

**Fecha**: 2026-06-20
**Fase**: Baseline estático y descubrimiento local (Fase 1). No incluye runtime Nav2 completo.

Este documento separa el estado de readiness del sandbox de navegación offline de OttoGuide en cuatro niveles independientes. Ningún nivel implica el siguiente.

## Niveles de readiness

| Nivel | Estado | Evidencia |
|---|---|---|
| `STATIC_BASELINE` | **READY** | Sandbox existente auditado (`offline_nav_sandbox.launch.py`, `nav2_offline_sandbox_params.yaml`); mapa sintético versionado creado y marcado `SYNTHETIC_TEST_MAP`/`NOT_UADE_MAP`/`NOT_METRICALLY_VALIDATED`/`NOT_FOR_PHYSICAL_NAVIGATION`; default del launch apunta al mapa versionado (no a `artifacts/`); verificador de aislamiento estático (`verify_sandbox_isolation.py`) implementado y en `PASS`; tests `unittest` puros (19/19 `OK`) sin ROS. |
| `LOCAL_ROS_CAPABILITIES` | **READY** | Matriz de paquetes ROS 2 locales verificada en WSL `Ubuntu-24.04` (ROS 2 `jazzy`) sin `apt`/`pip`/`rosdep`/Internet — ver [OFFLINE_NAVIGATION_LOCAL_CAPABILITIES.md](OFFLINE_NAVIGATION_LOCAL_CAPABILITIES.md). Todos los paquetes Nav2 base requeridos para fases posteriores están presentes, salvo `nav2_loopback_sim` (no instalado). |
| `ROS_RUNTIME_SANDBOX` | **NOT_READY** | No se levantó el stack Nav2 completo en esta fase. No se iniciaron nodos `planner_server`, `controller_server`, `behavior_server` ni `waypoint_follower`. Solo `map_server` + `lifecycle_manager` (+ RViz opcional) existían previamente y no fueron ejecutados en esta fase tampoco; esta fase fue exclusivamente estática (lectura de archivos, sin `ros2 run`/`ros2 launch`). |
| `PHYSICAL_NAVIGATION` | **NOT_READY** | Sin cambios respecto al estado previo. Depende de L2 y L3 validados, de calibración TF física, de mapa navegable completo y de los criterios de la sección 7 del plan original. No se conectó el robot ni se usó hardware físico en esta fase. |

## Estado de capas del sistema (sin cambios en esta fase)

| Nivel | Estado | Fuente |
|---|---|---|
| L0 sensores | READY | [PROGRESO_ODOMETRIA_OFFLINE.md](PROGRESO_ODOMETRIA_OFFLINE.md) |
| L1 intención/movimiento | READY | [PROGRESO_ODOMETRIA_OFFLINE.md](PROGRESO_ODOMETRIA_OFFLINE.md) |
| L2 odometría | **NOT_READY** | No existe trayectoria offline confiable; sin cambios en esta fase |
| L3 localización/mapa | **NOT_READY** | Depende de L2 validado; sin cambios en esta fase |
| Navegación física | **NOT_READY** | Depende de L2, L3, calibración TF y criterios de la sección 7 del plan |

## Lo que esta fase NO declara

- No declara autonomía validada.
- No declara mapa físico validado (el mapa sintético es exclusivamente para tests offline, no representa la UADE).
- No declara odometría validada.
- No declara Nav2 listo para el robot.
- No declara `ROS_RUNTIME_SANDBOX` ni `PHYSICAL_NAVIGATION` como `READY` o `PARTIAL`.

## Qué cambió respecto a la fase previa

- Se documentó por primera vez, con evidencia verificada localmente, qué paquetes Nav2 existen en el entorno de desarrollo.
- Se reemplazó la dependencia del launch en un artefacto local no versionado (`artifacts/maps/ottoguide_hil_stationary_map.yaml`) por un mapa sintético versionado y explícitamente no apto para navegación física.
- Se agregó un verificador de aislamiento estático reproducible y tests puros asociados.

## Próximo incremento

Habilitar `ROS_RUNTIME_SANDBOX` requiere, como mínimo: levantar el stack Nav2 completo (planner, controller, behaviors, waypoint follower) sobre el mapa sintético versionado en un entorno aislado (`ROS_LOCALHOST_ONLY=1`, `ROS_DOMAIN_ID` explícito), sin tocar hardware físico ni `/cmd_vel` real. Esa fase de runtime no se ejecutó aún y queda fuera del alcance de este incremento.
