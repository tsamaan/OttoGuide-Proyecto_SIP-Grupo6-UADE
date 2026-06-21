# ADR 002 — Reconciliación de contratos de navegación y hardware

**Estado**: Accepted
**Fecha**: 2026-06-21
**Fase**: Fase 2H.0 — Reconciliación de arquitecturas de navegación y hardware

## Contexto

El sandbox offline Nav2 (Fases 2A–2G) validó, sobre ROS 2 Jazzy en WSL,
una cadena completa y aislada: `map_server` → `planner_server` →
`controller_server` → `collision_monitor` → `behavior_server` →
`bt_navigator` (`NavigateToPose`) → `waypoint_follower`
(`FollowWaypoints`), todo bajo namespace real `/offline_nav`, sin
publicar velocidad fuera de `cmd_vel_raw`/`cmd_vel_safe`.

En paralelo, la aplicación OttoGuide (`main.py`, `TourOrchestrator`)
sigue corriendo sobre una arquitectura distinta y no integrada:
`AsyncNav2Bridge` (`src/navigation/nav2_bridge.py`), que envuelve
`nav2_simple_commander.robot_navigator.BasicNavigator` y publica/clampa
`/cmd_vel` → `/cmd_vel_nav`. Esta arquitectura nunca fue conectada ni
validada contra el sandbox offline.

Antes de decidir cómo (o si) conectar ambas arquitecturas, `TourOrchestrator`
dependía directamente de tipos concretos:

```python
hardware_api: RobotHardwareAPI          # src/hardware/, legacy
nav_bridge: AsyncNav2Bridge              # src/navigation/nav2_bridge.py, legacy
```

Esto acopla el orquestador a una implementación específica y hace que
cualquier futura migración de navegación (Fase 2H.1: cliente ROS 2
directo contra el sandbox) requiera tocar `TourOrchestrator` de nuevo.

## Problema

¿Cómo reducir el acoplamiento de `TourOrchestrator` a implementaciones
concretas de hardware y navegación, sin:

- cambiar su comportamiento funcional (FSM, timeouts, política de
  waypoints, manejo de emergencia);
- ejecutar runtime ROS ni tocar hardware;
- eliminar o reescribir el código legacy (`src/hardware/`,
  `AsyncNav2Bridge`) antes de que exista un reemplazo validado?

## Alternativas consideradas

1. **No hacer nada todavía** — postergar la reconciliación hasta tener
   la Fase 2H.1 completa. Descartado: implementar el cliente ROS 2
   directo (2H.1) sin haber desacoplado primero `TourOrchestrator`
   habría forzado a tocar la FSM dos veces (una vez para introducir el
   contrato, otra para cambiar la implementación), aumentando el riesgo
   de regresión funcional en cada paso.
2. **Migrar directamente a un cliente ROS 2 sin contrato intermedio** —
   reemplazar `AsyncNav2Bridge` por el futuro `DirectNav2ActionBridge`
   en el mismo cambio que toca `TourOrchestrator`. Descartado: mezcla
   dos riesgos (cambio de contrato + cambio de implementación de
   navegación con runtime ROS real) en un solo commit, violando el
   principio "una capacidad principal por fase" y dificultando el
   rollback si algo falla.
3. **Contrato `Protocol` abstracto (`NavigationPort`) + HAL ya existente
   (`RobotHardwareInterface`)** — elegida. Permite que
   `TourOrchestrator` dependa de tipos abstractos sin tocar ninguna
   implementación concreta, sin ejecutar ROS, y deja la migración real
   de navegación (2H.1) como un cambio aislado y reversible que solo
   necesita producir una nueva clase que conforme `NavigationPort`.

## Decisión

- `hardware/` (ya existente desde fases previas de hardware) queda
  formalizada como la HAL canónica única; `hardware.interface.RobotHardwareInterface`
  y `hardware.interface.MotionCommand` son los contratos canónicos.
  `src/hardware/` (con `RobotHardwareAPI`, `RobotHardwareAPIError`,
  `SupportsUnitreeHighLevelControl`) queda clasificada como **legacy,
  en cuarentena, sin nuevos consumidores de runtime**, pero no se
  elimina ni se reescribe.
- Se crea `src.navigation.port.NavigationPort`, un `Protocol`
  `runtime_checkable` con el contrato mínimo (`start`, `close`,
  `navigate_to_waypoints`, `send_goal`, `cancel_navigation`,
  `inject_absolute_pose`, `is_navigation_active`), importable sin
  `rclpy`/`cv2`/`nav2_simple_commander`.
- Se extraen `NavWaypoint`/`NavigationStatus` de `nav2_bridge.py` a un
  módulo puro nuevo, `src.navigation.models`, también sin imports de
  ROS, preservando compatibilidad de import desde `src.navigation` y
  `src.navigation.nav2_bridge` (mismo objeto de clase, no solo misma
  forma estructural).
- `TourOrchestrator` se retipa: `hardware_api: RobotHardwareInterface`,
  `nav_bridge: NavigationPort`. Deja de importar `src.hardware` y
  `AsyncNav2Bridge`. La instancia inyectada en runtime sigue siendo la
  misma (`AsyncNav2Bridge` legacy vía `main.py`); el comportamiento no
  cambia.
- `AsyncNav2Bridge`, `MockNav2Bridge` y `_MinimalNavStub` (en `main.py`)
  ya exponen o se actualizan para exponer los 7 métodos de
  `NavigationPort`, verificado con `isinstance()` real (no solo por
  inspección de nombres).
- La integración real de navegación contra el sandbox offline
  (`/offline_nav/navigate_to_pose`, `/offline_nav/follow_waypoints`) se
  posterga explícitamente a la Fase 2H.1.

## Consecuencias

**Positivas:**

- `TourOrchestrator` ya no necesita cambiar cuando se implemente el
  cliente ROS 2 directo en la Fase 2H.1; solo se necesita una nueva
  clase que conforme `NavigationPort`.
- `models.py`/`port.py` son importables y testeables sin ROS 2
  instalado, lo que permite verificación estática rápida en CI/Windows
  sin depender de WSL.
- La duplicación de `NavWaypoint`/`NavigationStatus` en múltiples
  módulos queda eliminada; existe una única fuente de verdad.

**Negativas / riesgos abiertos:**

- `AsyncNav2Bridge` sigue sin validar contra el sandbox offline; sigue
  publicando `/cmd_vel`/`/cmd_vel_nav` y dependiendo de
  `BasicNavigator`, ninguno de los cuales es la arquitectura canónica
  futura.
- `src/hardware/` permanece en el árbol del repositorio, duplicando
  responsabilidades con `hardware/`. El riesgo de que un desarrollador
  importe accidentalmente `src.hardware` en código nuevo se mitiga con
  el guard estático nuevo en `verify_sandbox_isolation.py` y con
  `test_architecture_reconciliation_contract.py`, pero no se elimina
  estructuralmente hasta que `src/hardware/` se borre.
- La política de waypoints del orquestador (un `NavigateToPose`/
  `navigate_to_waypoints` por waypoint, continuar si uno falla) no se
  resolvió en esta fase; queda pendiente para 2H.1/2I, documentada como
  legacy y sujeta a revisión.

## Plan de migración

1. **Fase 2H.0 (esta fase)**: contratos abstractos, sin cambio de
   comportamiento. Completada.
2. **Fase 2H.1**: implementar y validar DirectNav2ActionBridge de forma aislada.
   - Los métodos actuales conservarán sus retornos por compatibilidad:
     `send_goal(...) -> bool`
     `navigate_to_waypoints(...) -> bool`
     `cancel_navigation() -> None`
   - En 2H.1 se incorporarán modelos tipados de resultado.
   - En 2H.1 `NavigationPort` agregará:
     `get_status()`
     `get_last_result()`
   - El `bool` retornado será únicamente: `NavigationResult.succeeded`.
   - La migración de `main.py` al nuevo bridge NO pertenece a 2H.1.
3. **Fase 2H.2**: seleccionar e inyectar el bridge en main.py.
4. **Fase 2I**: política de misión, reintentos, skip, abort y handover.
5. **Sin fecha fija**: eliminar `src/hardware/` una vez confirmado que
   ningún test ni código de producción lo necesita.

## Criterios de rollback

- Si la Fase 2H.1 descubre que `NavigationPort` no puede expresar un
  requisito real del cliente ROS 2 directo (por ejemplo, necesidad de
  feedback estructurado más rico que un `bool`), el contrato se
  extiende de forma compatible (nuevos métodos opcionales o un segundo
  Protocol), nunca rompiendo `AsyncNav2Bridge`/`MockNav2Bridge`
  existentes sin actualizarlos en el mismo cambio.
- Si se detecta que el retipado de `TourOrchestrator` rompe algún
  consumidor no cubierto por los tests existentes, revertir el commit
  de esta fase es seguro: no se eliminó código, solo se cambiaron
  type hints, imports y la fuente de `NavWaypoint`/`NavigationStatus`
  (con compatibilidad de import preservada).

## Matriz de decisión

| Dominio        | Canónico                                          | Legacy                                 | Decisión             |
| -------------- | -------------------------------------------------- | --------------------------------------- | --------------------- |
| Entrypoint     | `main.py`                                          | entrypoints históricos                  | conservar `main.py`   |
| Orquestador    | `TourOrchestrator`                                 | alternativas históricas                 | conservar FSM         |
| HAL            | `hardware/`                                        | `src/hardware/`                         | `hardware/` canónico  |
| MotionCommand  | `hardware.interface.MotionCommand`                 | `src.hardware.interface.MotionCommand`  | canónico único        |
| Navegación     | futuro ActionClient directo                        | `AsyncNav2Bridge` + `BasicNavigator`    | migrar en 2H.1         |
| Velocidad      | `cmd_vel_raw → collision_monitor → cmd_vel_safe`   | `/cmd_vel → /cmd_vel_nav`               | conservar sandbox      |
| Waypoints      | `NavigateToPose` y `FollowWaypoints` según misión  | selección por `ROBOT_MODE`              | resolver en 2H.1        |
| Fallo waypoint | política fail-closed pendiente                     | continuar actualmente                   | resolver en 2H.1/2I     |

## Notas adicionales

- `duration_ms` en `MotionCommand` no constituye un watchdog de
  seguridad; es solo un parámetro de integración cinemática del
  adaptador mock/sim. No debe interpretarse como mecanismo de
  seguridad.
- `AsyncNav2Bridge` no está validado contra el sandbox offline
  (`/offline_nav/*`); su validación histórica es contra un stack ROS 2
  Foxy/Humble HIL distinto, documentado en `ROS2_INTEGRATION.md`.
- `BasicNavigator.followWaypoints()` es el cliente legacy de Simple
  Commander; permanece fuera de alcance de todas las fases del sandbox
  offline (2A–2G) y de esta fase (2H.0).
- El servidor `nav2_waypoint_follower` del sandbox offline está
  validado (Fase 2G) pero no está conectado a `TourOrchestrator`; esa
  conexión es exactamente el trabajo de la Fase 2H.1.
- No deben existir dos productores concurrentes de locomoción: durante
  `NAVIGATING`, Nav2 (o su futuro reemplazo canónico) es el único
  propietario del movimiento continuo; el HAL directo solo actúa como
  failsafe (`velocidad cero`, `damp()`, `emergency_stop()`) después de
  cancelar la navegación o en estado terminal.
- La interacción (`on_enter_interacting`) debe cancelar la navegación
  activa antes de emitir cualquier comando directo del HAL — este
  orden ya existía antes de esta fase y no se modificó.
- La navegación física continúa `NOT_READY`; nada en esta fase valida
  autonomía real ni seguridad física.
