# DirectNav2ActionBridge — Hardening Report (Fases 2H.1 y 2H.1.2)

## 1. Resumen ejecutivo

`DirectNav2ActionBridge` está implementado y validado de forma aislada
contra el sandbox offline (`/offline_nav/navigate_to_pose`,
`/offline_nav/follow_waypoints`). El runtime principal (`main.py`)
continúa usando `AsyncNav2Bridge` (legacy, basado en
`BasicNavigator`/Simple Commander). La selección del bridge directo como
implementación inyectada en producción corresponde a la **Fase
2H.2 — Main Runtime Navigation Bridge Selection**, todavía no
autorizada. Este documento describe el estado tras la **Fase 2H.1.2**,
que auditó el commit publicado por la Fase 2H.1.1 (`49a998c`), confirmó
defectos reales de ownership terminal/cancelación/timeout, los corrigió,
y completó evidencia runtime estricta de los cuatro contratos
funcionales del bridge.

Esta validación es exclusivamente un **offline ROS runtime smoke test**
sobre `offline_runtime_simulator.py` (odometría/scan sintéticos, sin
hardware). No es HIL (Hardware-In-the-Loop): ningún paso de esta fase
conectó al robot físico, a Unitree SDK, a Livox, ni a RealSense.

## 2. Baseline auditado

```
HEAD auditado    = 49a998c24b2300f7405709c36520cf60a9b63b9b
PARENT            = 8af4b4cff5519e26d5bb4361ca976e8da902f9fc
MENSAJE            = fix(nav): harden direct nav2 action bridge and
                      stabilize smoke tests (2H.1.1)
```

Ese commit ya estaba publicado en `origin`/`robot` antes de esta fase y
no fue modificado ni reescrito.

## 3. Defectos confirmados en 49a998c (auditoría 2H.1.2)

La auditoría reprodujo y confirmó los siguientes defectos reales en
`src/navigation/direct_nav2_action_bridge.py`:

1. **Auto-espera en timeout**: `_result_monitor_task`, en su rama de
   timeout, llamaba al método público `cancel_navigation()`, el cual a
   su vez esperaba `_active_result_task` — la misma tarea que estaba
   ejecutando esa llamada. Esto no producía un deadlock duro (el
   `wait_for` interno expiraba), pero violaba el principio de ownership
   única y desperdiciaba `cancel_terminal_timeout_s` innecesariamente.
2. **Limpieza inferida desde el enum local**: `_finalize_result` limpiaba
   `task_active`/`active_goal_handle` cuando `result.status` era
   `ERROR` o estaba en un conjunto fijo de estados, **sin im portar si
   el terminal remoto estaba realmente confirmado**. Una excepción local
   (p.ej. fallo de `get_result_async()`) se traducía en limpieza
   inmediata, perdiendo todo rastro de que el goal remoto podía seguir
   activo.
3. **Cancelación sin exigencia de `CANCELED`**: tras una cancelación
   aceptada, si el terminal resultante no era `CANCELED`, el código solo
   registraba un `LOGGER.warning(...)` y continuaba como si nada.
4. **Excepción posterior a aceptación tratada como limpieza segura**:
   si ocurría una excepción después de `goal_handle.accepted=True` (por
   ejemplo, fallo de `get_result_async()` o de creación de la tarea
   monitor), `_execute_action` finalizaba el resultado con
   `force_inactive=True` sin intentar cancelar el goal remoto.
5. **Goal-response timeout sin preservar evidencia**: ante un timeout
   esperando la respuesta de aceptación, el UUID generado localmente no
   se conservaba en `NavigationStatus`/`NavigationResult`, dificultando
   el diagnóstico del estado degradado.
6. **`except ImportError: pass` en `inject_absolute_pose`**: una
   dependencia de visión faltante (`cv2`) se silenciaba por completo,
   reportando éxito implícito sin haber publicado `/initialpose`.

## 4. Correcciones aplicadas (Fase 2H.1.2)

- **`_request_cancel_only()`** (nuevo helper interno): envía
  `CancelGoal`, valida `return_code`/UUID en `goals_canceling`, y
  actualiza `cancel_requested`/`cancel_accepted`. **Nunca** espera
  `_active_result_task`.
- **`cancel_navigation()`** (método público, único punto de entrada
  externo de cancelación): delega en `_request_cancel_only()` y luego
  espera al monitor de resultado. Si el terminal confirmado no es
  `CANCELED`, lanza `RuntimeError("CANCEL_TERMINAL_NOT_CANCELED:<STATUS>")`
  en vez de solo advertir.
- **`_result_monitor_task()`**: único propietario de la transición
  terminal normal. En sus ramas de timeout/excepción usa
  exclusivamente `_request_cancel_only()` (nunca el método público),
  evitando cualquier auto-espera.
- **`_finalize_result(result, terminal_confirmed)`**: ya no infiere
  terminación remota a partir del enum local. Solo limpia
  `task_active`/`active_goal_handle`/`active_goal_uuid` cuando el
  llamador aporta evidencia terminal comprobada
  (`terminal_confirmed=True`); en caso contrario marca
  `NavigationStatus.remote_state_unknown=True` y mantiene el goal
  activo, bloqueando nuevos goals hasta `close()`.
- **Excepción posterior a aceptación**: `_execute_action` ahora
  distingue si la excepción ocurrió antes o después de
  `goal_handle.accepted=True`. Después de la aceptación, solicita
  cancelación vía el helper interno, intenta confirmar `CANCELED` sobre
  el mismo result future, y solo limpia si se confirma; de lo
  contrario conserva el goal activo y `remote_state_unknown=True`.
- **Goal-response timeout**: conserva el UUID generado localmente en
  `NavigationStatus.goal_uuid`/`NavigationResult.goal_uuid`, marca
  `terminal_confirmed=False` (degradado, bloquea nuevos goals) y exige
  `close()` para recuperar el bridge.
- **`inject_absolute_pose`**: el `except ImportError: pass` fue
  eliminado. Una dependencia faltante ahora lanza
  `RuntimeError("INITIAL_POSE_DEPENDENCY_UNAVAILABLE:<detalle>")`.
- **`close()`/`_cleanup()`**: sigue siendo idempotente y libera siempre
  los recursos locales (executor/nodo/contexto/thread), pero ya no
  silencia un fallo de cancelación o de espera de terminal: si el
  estado remoto queda sin confirmar, lanza
  `RuntimeError("DIRECT_BRIDGE_CLOSE_REMOTE_STATE_UNKNOWN")` después de
  completar el teardown local.
- **`NavigationStatus.remote_state_unknown`** (nuevo campo en
  `src/navigation/models.py`): expone explícitamente cuándo el bridge
  no puede confirmar el estado remoto del último goal.

## 5. Tests unitarios

`tests/unit/test_direct_nav2_action_bridge.py` pasó de 32 a 44 tests.
Los 12 tests nuevos reproducen y verifican explícitamente cada defecto
de la sección 3: auto-espera del monitor, helper interno que no espera
el result task, cancelación pública que sí espera al monitor, terminal
post-cancel distinto de `CANCELED`, result timeout con/sin terminal
confirmado, excepción post-aceptación, `_finalize_result` sin limpiar
sin evidencia, goal-response timeout con UUID preservado y bloqueo de
un segundo goal, propagación de dependencia de pose faltante, callback
tardío sobre future cancelado, callback con loop cerrado, y no
exposición de objetos internos mutables. Ejecutados sin ROS instalado
mediante fakes locales (Windows) y bajo ROS 2 Jazzy real (WSL).

`tests/unit/test_offline_navigation_sandbox_isolation.py` agrega
`DirectNav2ActionBridgeOwnershipContractTests`: guards estáticos AST que
impiden que el monitor llame al método público de cancelación, exigen
la existencia del helper interno (y que este nunca referencie
`_active_result_task`), exigen que `cancel_navigation()` exija terminal
`CANCELED`, y prohíben `except ImportError: pass` en el archivo del
bridge.

## 6. Verificadores estáticos

`tools/hil/offline_navigation/verify_sandbox_isolation.py` agrega
`check_direct_nav2_action_bridge_ownership_contract`, ejecutado en modo
`--runtime` (el bridge solo se escanea en ese modo, igual que el resto
de `RUNTIME_SCAN_FILES`). `PASS` en Windows y WSL, modo estático y
runtime.

## 7. Smoke test runtime (rediseño 2H.1.2)

`tools/hil/offline_navigation/smoke_test_direct_nav2_action_bridge.py`
fue rediseñado: el proceso padre valida `--base-domain-id`/`--timeout`,
deriva cuatro `ROS_DOMAIN_ID` independientes, y lanza **cuatro procesos
hijos aislados** (uno por escenario, vía el flag interno `--scenario`,
no expuesto en el uso normal). Cada hijo inicializa `rclpy` una única
vez contra un único domain, levanta el sandbox vía el wrapper, crea un
`DirectNav2ActionBridge` y un observador de telemetría completamente
independiente (contexto, nodo y thread/executor propios, sin bloquear
el loop de asyncio con `spin_once`), ejecuta su escenario, cierra todo y
termina.

Se agregó inspección real del grafo del nodo del bridge
(`ros2 node info /offline_nav/direct_nav2_action_bridge`): se exige que
el nodo del bridge no tenga publishers/subscribers de
`/cmd_vel`/`/cmd_vel_nav`/`cmd_vel_raw`/`cmd_vel_safe` (ni namespaced),
y se confirma disponibilidad real de
`/offline_nav/navigate_to_pose`/`/offline_nav/follow_waypoints` vía
`ros2 action list`.

### Contratos validados (4 escenarios)

1. **NavigateToPose éxito**: goal dinámico `~0.50m` por delante de la
   pose inicial real. Exige `goal_accepted`, UUID no vacío,
   `feedback_count>0`, `>=2` muestras de `distance_remaining` con
   reducción neta, `SUCCEEDED`, `succeeded=True`, telemetría
   `raw`/`safe` no-cero, `distance_moved>0.05m`,
   `final_goal_distance<0.12m`, twists finales en cero, pose estable.
2. **NavigateToPose cancelación**: goal `~1.5m`. No cancela hasta
   observar feedback, reducción de `distance_remaining>=0.02m` y
   desplazamiento real `>0.02m`. Exige `cancel_requested`/`accepted`,
   UUID coincidente, `CANCELED`, `succeeded=False`, twists en cero,
   pose estable.
3. **FollowWaypoints éxito**: exactamente tres waypoints relativos
   `(0.30,0.00)`, `(0.30,0.20)`, `(0.00,0.20)`, interpretados como
   **desplazamientos acumulativos** (cada offset es relativo al
   waypoint anterior, no independientemente relativo al inicio) —
   misma resolución que ya usa, sin cambios, el
   `smoke_test_offline_waypoint_follower.py` validado en Fase 2G para
   idéntica tupla de offsets. Tratarlos como independientes del inicio
   exige un giro en el lugar cercano a 180° en el tercer tramo, que el
   `movement_time_allowance=10.0s`/critic `Oscillation` del
   `controller_server` (sin recoveries en el árbol BT) no completa.
   Exige progresión de feedback normalizada exactamente `[0,1,2]`,
   `SUCCEEDED`, `missed_waypoints=[]`, telemetría no-cero, movimiento
   observado, distancia final dentro de tolerancia, twists finales en
   cero, pose estable.
4. **FollowWaypoints inalcanzable**: waypoint 0 alcanzable, waypoint 1
   absoluto `(5.0, 5.0)` (fuera del mapa), waypoint 2 alcanzable. Exige
   `ABORTED` (nunca `TIMEOUT` reinterpretado como fallo),
   `missed_waypoints` con índice 1 exacto, `error_code=204`
   (`GOAL_OUTSIDE_MAP`), feedback que nunca progresa al índice 2,
   twists en cero, pose estable.

### Evidencia runtime (dos corridas oficiales, sin cambios de código)

| Escenario | Run 1 (base 220) | Run 2 (base 224) |
|---|---|---|
| NavigateToPose éxito | PASS — `feedback_count=474`, `distance_sample_count=13`, `final_goal_distance≈0.074m` | PASS — `feedback_count=474`, `distance_sample_count=13`, `final_goal_distance≈0.072m` |
| NavigateToPose cancel | PASS — `cancel_accepted=true`, terminal `CANCELED`, reducción `distance_remaining≈0.050m` | PASS — idéntico patrón, terminal `CANCELED` |
| FollowWaypoints éxito | PASS — progresión `[0,1,2]`, `missed_waypoints=[]`, `final_goal_distance≈0.059m` | PASS — idéntico |
| FollowWaypoints inalcanzable | PASS — `ABORTED`, `missed_waypoints={"1":204}`, nunca progresa a índice 2 | PASS — idéntico |

Ambas corridas confirmaron `orphan_processes=0` en todos los
escenarios y cero cambios de código/configuración entre ellas. Un
intento intermedio de Run 2 sufrió una carrera de timing transitoria
bajo carga WSL (componentes del sandbox no llegaron a `active` a
tiempo, sin relación con el bridge) — el mismo patrón ya documentado en
`OFFLINE_NAVIGATION_SANDBOX_READINESS.md` para fases anteriores; se
resolvió repitiendo la corrida sin tocar código, tal como en esos
precedentes.

### Regresiones

`smoke_test_offline_bt_navigator.py` (`--base-domain-id 180`) y
`smoke_test_offline_waypoint_follower.py` (`--base-domain-id 200`) —
ambos sin modificar — continúan en `PASS` tras estos cambios.

## 8. Limitaciones

- Esta validación es exclusivamente offline/sintética
  (`offline_runtime_simulator.py`); no constituye evidencia de
  navegación física ni de seguridad física
  (`NOT_FOR_PHYSICAL_SAFETY_VALIDATION`).
- El bridge directo permanece **desconectado** de `main.py`/
  `TourOrchestrator`. `MAIN_RUNTIME_MIGRATED=NO`,
  `LEGACY_NAVIGATION_RUNTIME_ACTIVE=YES`. La selección del bridge en el
  runtime principal es exclusivamente trabajo de la Fase 2H.2, todavía
  no autorizada.
- No existe ningún script versionado de "diagnóstico oficial de dos
  corridas" aparte de invocar el smoke test dos veces con distinto
  `--base-domain-id`, como se hizo en la sección 7.
- La política de reintento/skip/abort de waypoints fallidos a nivel de
  misión sigue pendiente para la Fase 2I.

## 9. Próximo incremento

El chat principal debe auditar el commit de la Fase 2H.1.2 y decidir si
se autoriza la **Fase 2H.2 — Main Runtime Navigation Bridge
Selection**. La política de misión de la Fase 2I no debe iniciarse
todavía.
