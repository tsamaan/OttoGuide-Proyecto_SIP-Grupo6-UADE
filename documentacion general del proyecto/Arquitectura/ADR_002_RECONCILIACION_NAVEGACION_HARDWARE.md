# ADR 002 — Reconciliación de contratos de navegación y hardware

**Estado**: Accepted
**Fecha**: 2026-06-21
**Fase**: Fase 2H.0 — Reconciliación de arquitecturas de navegación y hardware

> ## ➕ ADDENDUM 2H.2.3 (2026-06-22) — confirmación, no cambio de decisión
>
> La Fase 2H.2.3 (corrección de evidencia) **no altera** esta ADR; la confirma.
> El plano de misión sigue siendo Nav2 (`bt_navigator`/`waypoint_follower` →
> `cmd_vel_raw` → `collision_monitor` → `cmd_vel_safe`); Unitree NO sustituye a
> Nav2. El plano Unitree futuro (HAL/seguridad/modos/telemetría/damp/locomoción/
> DDS·SDK2) permanece **no integrado** en esta fase. No se introdujo SDK2 ni
> hardware Unitree. La preparación física quedó exclusivamente como un paquete
> **P0 read-only** (`tools/hil/physical_read_only/`), `PREPARED_NOT_AUTHORIZED`,
> `NOT_EXECUTED`. `PHYSICAL_MOVEMENT = NOT_AUTHORIZED`. Ver
> `MAIN_RUNTIME_NAVIGATION_SELECTION_2H23_EVIDENCE_CORRECTION_REPORT.md`.

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
  `runtime_checkable` con el contrato mínimo en 2H.0 (`start`, `close`,
  `navigate_to_waypoints`, `send_goal`, `cancel_navigation`,
  `inject_absolute_pose`, `is_navigation_active`; 7 métodos en esta
  fase), importable sin `rclpy`/`cv2`/`nav2_simple_commander`. La Fase
  2H.1 agrega `get_status()` y `get_last_result()`: desde entonces el
  contrato vigente tiene **9 métodos**, no 7 (ver corrección explícita
  más abajo).
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
  ya exponen o se actualizan para exponer los **9 métodos** vigentes de
  `NavigationPort` (`start`, `close`, `navigate_to_waypoints`,
  `send_goal`, `cancel_navigation`, `inject_absolute_pose`,
  `is_navigation_active`, `get_status`, `get_last_result`), verificado
  con `isinstance()` real (no solo por inspección de nombres).
  `DirectNav2ActionBridge` (Fase 2H.1) también conforma los 9.
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
  resolvió en esta fase. Las Fases 2H.1/2H.1.2/2H.1.3/2H.1.4/2H.1.5
  validaron `DirectNav2ActionBridge` de forma aislada sin tocar esta
  política, y la Fase 2H.2 inyectó el selector de backend sin tocarla
  tampoco; queda pendiente para 2I, documentada como legacy y sujeta a
  revisión.

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
3. **Fase 2H.1.2**: auditoría del commit publicado por 2H.1.1
   (`49a998c`), corrección de defectos reales de ownership del estado
   terminal, cancelación, timeouts y estado remoto desconocido en
   `DirectNav2ActionBridge`, y evidencia runtime estricta de los cuatro
   contratos (`NavigateToPose` éxito/cancelación,
   `FollowWaypoints` éxito/inalcanzable) en dos corridas oficiales
   independientes. Completada — ver
   `DIRECT_NAV2_ACTION_BRIDGE_2H1_REPORT.md`. Sigue siendo
   exclusivamente validación aislada: `DirectNav2ActionBridge` continúa
   desconectado de `main.py`/`TourOrchestrator`.
   `MAIN_RUNTIME_MIGRATED=NO`, `LEGACY_NAVIGATION_RUNTIME_ACTIVE=YES`.
4. **Fase 2H.1.3**: microincremento aditivo que cierra brechas
   puntuales detectadas tras 2H.1.2: detección de estado remoto
   desconocido preexistente en `close()`, propagación de errores de
   cleanup en el smoke (sin silenciarlos), validación estricta del
   escenario `FollowWaypoints` inalcanzable (nunca acepta `REJECTED`),
   integridad/frescura de los JSON de los procesos hijos del smoke,
   verificación real del cierre del thread del observer, y manejo
   seguro de un PGID potencialmente sin inicializar. Completada — ver
   `DIRECT_NAV2_ACTION_BRIDGE_2H1_REPORT.md`, sección 8. Sigue siendo
   exclusivamente validación aislada; sin cambios en
   `MAIN_RUNTIME_MIGRATED`/`LEGACY_NAVIGATION_RUNTIME_ACTIVE`.
5. **Fase 2H.1.4**: microincremento aditivo que corrige
   `cancel_navigation()` cuando existe un goal aceptado pero ningún
   result task observable (CancelGoal aceptado nunca se traduce en
   `CANCELED` sin un monitor que confirme el `GoalStatus` real; ahora
   lanza `CANCEL_TERMINAL_UNOBSERVABLE` y preserva
   `remote_state_unknown=True`), y prepara el handoff operativo
   `PREFLIGHT_DIRECT_NAV2_ACTION_BRIDGE_PHYSICAL_VALIDATION.md` para una
   futura sesión física. Completada — ver
   `DIRECT_NAV2_ACTION_BRIDGE_2H1_REPORT.md`, sección 9. Sigue siendo
   exclusivamente validación aislada; no se ejecutó ningún comando sobre
   hardware físico.
6. **Fase 2H.1.5**: microincremento aditivo final de la serie 2H.1 que
   corrige `cancel_navigation()` cuando existe navegación activa pero
   ningún goal handle alcanzable (p.ej. tras un goal-response timeout;
   ahora lanza `CANCEL_GOAL_HANDLE_UNAVAILABLE` y preserva
   `remote_state_unknown=True`, sin solicitar `CancelGoal` ni esperar un
   `result_task` remanente como sustituto), cerrando la matriz pública
   completa de estados de cancelación. Completada — ver
   `DIRECT_NAV2_ACTION_BRIDGE_2H1_REPORT.md`, sección 10. Sigue siendo
   exclusivamente validación aislada; no se ejecutó ningún comando sobre
   hardware físico. Con esta fase, la serie 2H.1 queda documentada como
   cerrada.
7. **Fase 2H.2**: selector explícito y fail-closed del backend de
   navegación en `main.py` (`legacy`/`direct`/`stub`, resuelto desde
   `NAVIGATION_BACKEND`/`ROBOT_MODE`), interlock cerrado por defecto para
   bloquear `direct` contra hardware real
   (`NAVIGATION_DIRECT_REAL_ENABLED=False`), factory sin fallback
   silencioso a stub, y observabilidad del backend en `/status`. El
   default de producción no cambia: `ROBOT_MODE=real` sigue resolviendo a
   `AsyncNav2Bridge` salvo selección explícita. Completada — ver
   `MAIN_RUNTIME_NAVIGATION_SELECTION_2H2_REPORT.md`. La validación
   runtime completa de los cuatro escenarios de aplicación
   (`boot_shutdown`/`tour_success`/`interaction_cancel`/
   `emergency_cancel`) se completó en la sesión de recuperación 2H.2-R
   (2026-06-22): diagnóstico PASS (192–195), corrida oficial 1 PASS
   (204–207), corrida oficial 2 PASS (216–219), todos con `--timeout 150`;
   ver sección 9.4 del reporte. No se ejecutó ningún comando sobre
   hardware físico.
8. **Fase 2H.2.1**: microincremento aditivo de hardening sobre la
   selección de backend: corrección fail-closed de
   `_resolve_readiness_errors()` y `_resolve_navigation_observability()`
   cuando `get_status` está ausente o no es callable (antes silenciaban
   la condición; ahora bloquean tours con el error literal
   `"navigation status unavailable:missing"` y marcan
   `remote_state_unknown=True` respectivamente), eliminación de los
   decoradores `@skipUnless` de las cinco clases de test centrales
   (sustituidos por `_fake_settings()` y `_install_router_fakes()`),
   test de importación con dependencias bloqueadas, guards estáticos en
   `verify_sandbox_isolation.py` para las tres garantías nuevas, y
   rediseño del smoke test padre/hijo con `Popen`, control file atómico
   y escalado completo de señales en timeout. Completada — ver
   `MAIN_RUNTIME_NAVIGATION_SELECTION_2H21_HARDENING_REPORT.md`.
   Corrida oficial 1 PASS (196–199), corrida oficial 2 PASS parcial
   (224–227: 3/4, la cuarta falló por startup timing del sandbox, no por
   el selector); todos con `--timeout 150`. No se ejecutó ningún comando
   sobre hardware físico.
9. **Fase 2H.2.2**: microincremento aditivo de hardening sobre el smoke
   test de selección de backend: aislamiento de grupo de proceso
   (`start_new_session=True`, nunca `preexec_fn`), lease de limpieza
   criptográfico (token `secrets.token_hex(32)` + `secrets.compare_digest()`,
   directorio `0700`/archivo `0600` con `O_CREAT|O_EXCL|O_NOFOLLOW`),
   validación de identidad de kernel via `/proc/<pid>/stat` (pid, ppid,
   pgid, sid, start_ticks, uid) revalidada antes de cada señal, escalada
   de señales fail-closed (SIGINT→SIGTERM→SIGKILL) con `reap_callback`
   para evitar falsos "grupo vivo", gates de threads/zombies/huérfanos
   propios, startup determinístico del sandbox con deadline compartido,
   un guard estático nuevo (`check_main_runtime_cleanup_lease_contract`)
   y una suite de tests POSIX nueva
   (`test_main_runtime_timeout_cleanup.py`). Completada — ver
   `MAIN_RUNTIME_NAVIGATION_SELECTION_2H22_HARDENING_REPORT.md`.
   Diagnóstico 1 FAIL-PARTIAL (140–143: 1/4, intermitencia de entorno),
   diagnóstico 2 PASS (150–153: 4/4, mismo código, confirma
   intermitencia), corrida oficial 1 PASS (160–163: 4/4), corrida
   oficial 2 PASS (170–173: 4/4); todos con `--timeout 150`. No se
   ejecutó ningún comando sobre hardware físico.
10. **Fase 2I (pendiente, no autorizada)**: política de misión,
    reintentos, skip, abort y handover.
11. **Sin fecha fija**: eliminar `src/hardware/` una vez confirmado que
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
| Navegación     | `DirectNav2ActionBridge` (seleccionable via `NAVIGATION_BACKEND=direct`, 2H.2) | `AsyncNav2Bridge` (default real, `BasicNavigator`) | selector ya inyectado, default sin cambios |
| Velocidad      | `cmd_vel_raw → collision_monitor → cmd_vel_safe`   | `/cmd_vel → /cmd_vel_nav`               | conservar sandbox      |
| Waypoints      | `NavigateToPose` y `FollowWaypoints` según misión  | selección por `ROBOT_MODE`              | resolver en 2I           |
| Fallo waypoint | política fail-closed pendiente                     | continuar actualmente                   | resolver en 2I            |

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
