# DirectNav2ActionBridge — Hardening Report (Fases 2H.1, 2H.1.2, 2H.1.3, 2H.1.4 y 2H.1.5)

## 1. Resumen ejecutivo

`DirectNav2ActionBridge` está implementado y validado de forma aislada
contra el sandbox offline (`/offline_nav/navigate_to_pose`,
`/offline_nav/follow_waypoints`). El runtime principal (`main.py`)
continúa usando `AsyncNav2Bridge` (legacy, basado en
`BasicNavigator`/Simple Commander). La selección del bridge directo como
implementación inyectada en producción corresponde a la **Fase
2H.2 — Main Runtime Navigation Bridge Selection**, todavía no
autorizada. Este documento describe el estado tras la **Fase 2H.1.5**,
microincremento aditivo final de la serie 2H.1 que corrigió
`cancel_navigation()` para el caso en que existe navegación activa pero
no existe ningún goal handle con el que enviar `CancelGoal` (p.ej. tras
un goal-response timeout), cerrando así la matriz pública completa de
estados de cancelación. Las Fases 2H.1/2H.1.2/2H.1.3/2H.1.4 ya habían
auditado y corregido los defectos de ownership terminal/cancelación/
timeout/cierre degradado descritos más abajo; esta fase no los reaudita,
solo agrega el último caso faltante al mismo contrato de ownership y
tests de regresión que preservan todo lo anterior. Con 2H.1.5 en `PASS`,
la serie 2H.1 queda documentada como cerrada.

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

## 8. Fase 2H.1.3 — Close degraded-state and harden smoke evidence

Microincremento aditivo sobre la Fase 2H.1.2. No reaudita ownership
terminal/cancelación/timeout (ya `PASS`); cierra seis brechas puntuales
detectadas tras esa fase:

1. **`_cleanup()` no detectaba degradación preexistente al entrar.**
   Si `remote_state_unknown` ya era `True` (p.ej. tras un goal-response
   timeout, que nunca crea un goal handle ni un result task), o si
   `task_active=True` sin un handle, `close()` podía completar sin
   lanzar `DIRECT_BRIDGE_CLOSE_REMOTE_STATE_UNKNOWN` porque el código
   solo computaba `degraded` a partir de fallos *reactivos* de
   cancelación/espera. Corregido: `degraded` se computa primero desde
   el estado ya existente, antes de cualquier intento reactivo. Un
   cierre degradado es idempotente en efectos (no repite recursos) pero
   puede volver a reportar la misma degradación en llamadas
   posteriores, según lo autorizado por el encargo de esta fase.
2. **El smoke silenciaba errores de `bridge.close()`** con
   `except Exception: pass`. Corregido: se registra
   `BRIDGE_CLOSE_FAILED:<detalle>` y el escenario no puede dar `PASS`.
3. **`TelemetryObserver.shutdown()` no verificaba el thread tras
   `join()`.** Corregido: comprueba `is_alive()` después del join y
   lanza `OBSERVER_THREAD_STILL_ALIVE` (nunca silenciado); fallos no
   críticos de executor/nodo/contexto se acumulan y reportan juntos
   como `OBSERVER_SHUTDOWN_FAILED:<detalle>`.
4. **`_shutdown_and_count_orphans()` podía usar un `pgid` sin
   inicializar** si `os.getpgid()` fallaba. Corregido: `pgid` se
   inicializa explícitamente a `None`; un `ProcessLookupError` al
   resolver el PGID se trata como proceso ya terminado (0 huérfanos),
   nunca como una condición a reintentar contra un identificador no
   resuelto.
5. **El escenario `fw_unreachable` aceptaba `REJECTED` como
   equivalente a `ABORTED`** y podía retornar temprano sin validar el
   contrato completo si el polling local nunca observó
   `task_active=True` (el goal puede abortar antes de la primera
   iteración). Corregido: se extrajo un validador puro
   (`_validate_fw_unreachable_result`) que siempre exige `ABORTED`
   (nunca `REJECTED`/`TIMEOUT`/`ERROR`), índice de waypoint perdido `1`,
   `error_code=204`, ausencia de progreso al índice `2`, y
   `navigation_task_result=False`; la espera ahora se basa en
   `nav_task.done()`, cubriendo tanto el abort instantáneo como el
   normal, sin ninguna rama de retorno temprano que omita la
   validación.
6. **Los JSON de los procesos hijos del smoke usaban una ruta fija**
   (`..._child_{name}_{domain}.json`), reutilizable entre invocaciones,
   sin validar identidad ni coherencia de exit code. Corregido: cada
   invocación construye una ruta única (PID del padre + `time.time_ns()`
   + escenario + dominio) que debe no existir antes de lanzar el hijo;
   tras la ejecución se exige que el archivo exista, sea JSON válido, y
   que `scenario`/`domain_id` coincidan con lo solicitado y que
   `ok`/`returncode` sean consistentes (`CHILD_OUTPUT_PREEXISTING`,
   `CHILD_OUTPUT_MISSING`, `CHILD_OUTPUT_INVALID_JSON`,
   `CHILD_SCENARIO_MISMATCH`, `CHILD_DOMAIN_MISMATCH`,
   `CHILD_EXIT_CODE_MISMATCH`).

### Tests

`tests/unit/test_direct_nav2_action_bridge.py` pasó de 44 a 47 tests
(3 nuevos: close con degradación preexistente y result task ya
terminada, close tras goal-response timeout, close limpio llamado dos
veces). `tests/unit/test_offline_navigation_sandbox_isolation.py`
agrega dos clases nuevas: `DirectNav2ActionBridgeCloseDegradedContractTests`
(guard estático del punto 1) y
`DirectNav2ActionBridgeSmokeHardeningContractTests` (guards estáticos de
los puntos 2–6, más tests directos de los helpers puros extraídos del
smoke: `_validate_child_result`, `_build_child_output_path`,
`_validate_fw_unreachable_result`, y `TelemetryObserver.shutdown()`
instanciado sin ROS vía `__new__` + mocks).

### Verificadores estáticos

`verify_sandbox_isolation.py` agrega
`check_direct_nav2_action_bridge_close_degraded_contract` y
`check_direct_nav2_action_bridge_smoke_hardening_contract`, ambos
`PASS` en Windows y WSL, modo estático y runtime.

### Evidencia runtime (dos corridas oficiales, sin cambios de código)

Diagnóstico (`--base-domain-id 212`): `PASS` en el primer intento, los
cuatro escenarios sin errores.

| Escenario | Run 1 (base 220) | Run 2 (base 224) |
|---|---|---|
| NavigateToPose éxito | PASS | PASS |
| NavigateToPose cancel | PASS | PASS |
| FollowWaypoints éxito | PASS | PASS |
| FollowWaypoints inalcanzable | PASS | PASS |

Run 2 sufrió, en un primer intento, la misma carrera de timing
transitoria bajo carga WSL ya documentada para fases anteriores
(componentes del sandbox sin activarse a tiempo, 1 proceso huérfano sin
relación con el bridge ni con esta fase); se resolvió limpiando el
proceso huérfano y repitiendo la corrida completa sin ningún cambio de
código ni configuración. Las regresiones de BT Navigator (`PASS`) y
Waypoint Follower también sufrieron, de forma independiente, el mismo
patrón transitorio una vez cada una, resuelto del mismo modo.

## 9. Fase 2H.1.4 — Guard cancel without result monitor and freeze pre-physical validation handoff

### Defecto

Estado posible: `task_active=True`, `_active_goal_handle != None`,
`_active_result_task = None`. Surge cuando un goal es aceptado por el
servidor pero `get_result_async()` o la creación de la tarea monitor
fallan antes de producir un result task (handle y UUID se conservan;
`remote_state_unknown=True`, ya cubierto por 2H.1.2/2H.1.3).
`cancel_navigation()`, en ese estado, llamaba a `_request_cancel_only()`
(que sí podía aceptar el `CancelGoal` remotamente) y luego, al no
encontrar un `res_task` que esperar, **retornaba normalmente** —
afirmando implícitamente una cancelación terminada que nunca fue
observada.

### Riesgo

Una respuesta `CancelGoal` aceptada es evidencia de que el servidor
**recibió** la solicitud, nunca de que el goal efectivamente alcanzó el
`GoalStatus` terminal `CANCELED`. Sin un monitor de resultado que
observe ese `GoalStatus` real, tratar la aceptación del servicio como
"cancelación confirmada" es exactamente el mismo tipo de inferencia sin
evidencia que las Fases 2H.1.2/2H.1.3 ya habían eliminado para otras
rutas (timeout de resultado, excepción posterior a la aceptación,
goal-response timeout). Esta ruta había quedado sin cubrir.

### Corrección

`cancel_navigation()` ahora distingue explícitamente la ausencia de
result task **después** de ejecutar y validar
`_request_cancel_only()`: si `res_task is None`, marca
`remote_state_unknown=True` y lanza
`RuntimeError("CANCEL_TERMINAL_UNOBSERVABLE")`, sin inventar ningún
terminal, sin limpiar `active_goal_handle`/`active_goal_uuid`, y sin
crear una tarea monitor falsa. `task_active` permanece `True`, por lo
que `_execute_action` sigue bloqueando nuevos goals
(`NAVIGATION_GOAL_ALREADY_ACTIVE`) hasta `close()`. La ruta con result
task presente (resuelto a `CANCELED` o a cualquier otro terminal) no se
modificó: sigue exigiendo `CANCELED` exacto vía
`CANCEL_TERMINAL_NOT_CANCELED`, ya validado en 2H.1.2.

`_cleanup()` no requirió ningún cambio: ya detectaba degradación
preexistente desde `remote_state_unknown`/`task_active` sin handle
(fix de 2H.1.3), por lo que un `close()` posterior a
`CANCEL_TERMINAL_UNOBSERVABLE` completa el teardown local y relanza
`DIRECT_BRIDGE_CLOSE_REMOTE_STATE_UNKNOWN` sin rediseño adicional.

### Tests

`tests/unit/test_direct_nav2_action_bridge.py` pasó de 47 a 52 tests: 5
nuevos cubren cancel aceptado sin monitor (`CANCEL_TERMINAL_UNOBSERVABLE`
con todo el estado preservado), bloqueo del segundo goal, `close()`
posterior con teardown completo, y dos regresiones explícitas (cancel
con monitor presente que NO debe disparar el nuevo guard; cancel con
monitor presente y terminal distinto de `CANCELED` que debe seguir
disparando `CANCEL_TERMINAL_NOT_CANCELED`, nunca el nuevo error).
`tests/unit/test_offline_navigation_sandbox_isolation.py` agrega tres
tests AST nuevos a `DirectNav2ActionBridgeOwnershipContractTests`: el
patrón prohibido (`if res_task: ... ` sin rama explícita para `None`,
incluso con menciones sueltas de las cadenas correctas en comentarios)
debe rechazarse; la forma corregida debe aceptarse limpia.

### Verificador estático

`verify_sandbox_isolation.py` extiende
`check_direct_nav2_action_bridge_ownership_contract` con cuatro checks
nuevos sobre `cancel_navigation()`: presencia de
`CANCEL_TERMINAL_UNOBSERVABLE`, presencia de `remote_state_unknown`,
existencia de una comprobación explícita `res_task is None`/`not
res_task` (AST, no texto), y rechazo de un `if res_task:` sin rama
`else` cuando no existe esa comprobación explícita en otro lugar del
método. `PASS` en Windows y WSL, modo estático y runtime.

### Regresión offline dirigida

`smoke_test_direct_nav2_action_bridge.py --scenario ntp_cancel
--base-domain-id 228` (camino normal de cancelación, con result task
real): `PASS` en el primer intento — `cancel_requested=true`,
`cancel_accepted=true`, terminal `CANCELED`,
`navigation_task_result=false`, `orphan_processes=0`. La rama sin
result monitor no se fabricó contra el servidor ROS real (no tiene
sentido fabricarla artificialmente ahí); se valida exclusivamente por
unit tests, como exige el encargo de esta fase. No se repitieron los
cuatro escenarios completos ni las regresiones de BT Navigator/Waypoint
Follower: ni el smoke runtime ni el offline runtime simulator ni
`launch/`/`config/navigation/` cambiaron en esta fase.

### Handoff físico

Se creó
`documentacion general del proyecto/Operaciones_HIL/PREFLIGHT_DIRECT_NAV2_ACTION_BRIDGE_PHYSICAL_VALIDATION.md`,
un documento de handoff operativo (no una validación) que reutiliza
conceptualmente `HIL_TESTING_PROTOCOL.md` y
`PREFLIGHT_PROXIMA_SESION_FISICA_ODOM_TF.md`. Define bloqueos NO-GO
explícitos, un preflight read-only futuro (sin goals, sin velocidad, sin
`damp`, sin Nav2 físico), una matriz P0–P3, qué evidencia deberá
guardarse, y un rollback futuro definido pero no ejecutado. No se
ejecutó ningún comando sobre el robot físico durante esta fase.

### Limitaciones de esta fase

- Ningún paso de esta fase tocó hardware físico ni cambió
  `PHYSICAL_NAVIGATION` (permanece `NOT_READY`).
- El handoff físico es exclusivamente preparatorio: los bloqueos `NO-GO`
  que documenta no se resuelven con código ni con este informe.
- La compatibilidad ROS 2 Foxy/Jazzy (sandbox offline en Jazzy, robot
  físico en Foxy) sigue sin resolverse y queda explícitamente listada
  como bloqueo en el handoff.

## 10. Fase 2H.1.5 — Guard cancel when active goal handle is unavailable

### Estado defectuoso

Estado posible: `task_active=True`, `_active_goal_handle = None`,
`_active_result_task = None`, `_status.goal_uuid` con el UUID generado
localmente. Surge típicamente tras un goal-response timeout (la
aceptación remota nunca se confirma; nunca llega a existir un goal
handle ni un result task). El guard previo a esta fase era:

```python
if not goal_handle or not self._status.task_active:
    return
```

Esta condición combinada con `or` confunde dos situaciones distintas
("no hay navegación activa" y "navegación activa pero sin handle
alcanzable") en un único retorno silencioso. `cancel_navigation()`
retornaba normalmente sin haber podido enviar `CancelGoal` ni observar
ningún estado terminal.

### Por qué la ausencia de handle impide enviar `CancelGoal` y por qué no se puede inferir cancelación

Sin un `goal_handle` no existe ningún objeto remoto contra el cual
invocar `cancel_goal_async()`: no hay solicitud que enviar, y por lo
tanto no hay aceptación ni rechazo que observar. Inferir "cancelado" (o
cualquier otro terminal) a partir de la ausencia de handle sería el
mismo tipo de inferencia sin evidencia que las Fases 2H.1.2/2H.1.3/
2H.1.4 ya habían eliminado para otras rutas (timeout de resultado,
excepción posterior a la aceptación, aceptación de `CancelGoal` sin
monitor). Un `result_task` remanente tampoco sustituye esa solicitud
nunca enviada: esperarlo sería confirmar un terminal que nunca fue
provocado por esta llamada a `cancel_navigation()`.

### Matriz pública de cancelación (cerrada en esta fase)

| `task_active` | `goal_handle` | `result_task` | Comportamiento |
| --- | --- | --- | --- |
| `False` | cualquiera | cualquiera | retorno normal |
| `True` | `None` | cualquiera | `CANCEL_GOAL_HANDLE_UNAVAILABLE`, `remote_state_unknown=True` |
| `True` | presente | `None` | solicita cancelación; `CANCEL_TERMINAL_UNOBSERVABLE` (2H.1.4) |
| `True` | presente | presente | solicita cancelación, espera, exige `CANCELED` (2H.1.2) |

### Corrección

`cancel_navigation()` ahora separa el guard en dos comprobaciones
explícitas: primero `task_active=False` retorna normalmente en
solitario; luego, solo si hay navegación activa, `goal_handle is None`
marca `remote_state_unknown=True` y lanza
`RuntimeError("CANCEL_GOAL_HANDLE_UNAVAILABLE")` sin llamar a
`_request_cancel_only()`, sin tocar `task_active`/`goal_uuid`/
`active_result_task`, y sin crear ningún handle o result task
sintético. Las ramas con handle presente (con o sin result task) no se
modificaron: siguen siendo exactamente el contrato de 2H.1.2/2H.1.4.
`_cleanup()` no requirió ningún cambio: ya detectaba esta degradación
desde `task_active=True` sin handle (fix de 2H.1.3).

### Tests

`tests/unit/test_direct_nav2_action_bridge.py` pasó de 52 a 57 tests: 5
nuevos cubren cancelación sin navegación activa (no debe ni intentar
`_request_cancel_only()`), reproducción real del defecto vía un
goal-response timeout genuino seguido de `cancel_navigation()`
(`CANCEL_GOAL_HANDLE_UNAVAILABLE` con UUID preservado), bloqueo de un
segundo goal, `close()` posterior con teardown completo, y un estado
inconsistente con `result_task` presente pero sin handle (debe seguir
exigiendo el guard de ausencia de handle, sin esperar el `result_task`
como sustituto).

### Guard estático

`verify_sandbox_isolation.py` extiende
`check_direct_nav2_action_bridge_ownership_contract` con checks AST
nuevos sobre `cancel_navigation()`: presencia de
`CANCEL_GOAL_HANDLE_UNAVAILABLE`; existencia de un `if` aislado sobre
`task_active` (no combinado con `goal_handle` vía `or`) que retorna
normalmente; existencia de un `if goal_handle is None`/`not goal_handle`
explícito cuyo cuerpo contiene un `raise`; y rechazo explícito de la
combinación `if not goal_handle or not task_active: return` (el defecto
literal de esta fase). `PASS` en Windows y WSL, modo estático y runtime.

### Regresión offline dirigida

`smoke_test_direct_nav2_action_bridge.py --scenario ntp_cancel
--base-domain-id 228` (camino normal de cancelación, con handle y
result task reales): `PASS` en el primer intento —
`cancel_requested=true`, `cancel_accepted=true`, terminal `CANCELED`,
`navigation_task_result=false`, `orphan_processes=0`. La rama sin
handle se valida exclusivamente por unit tests reproduciendo el
goal-response timeout real, como exige el encargo de esta fase; no se
fabricó contra el servidor ROS real ni se repitieron los cuatro
escenarios completos ni las regresiones de BT Navigator/Waypoint
Follower, porque ni el smoke runtime ni el offline runtime simulator ni
`launch/`/`config/navigation/` cambiaron en esta fase.

### Cierre de la serie 2H.1

Con todos los gates de 2H.1.5 en `PASS`, la serie completa
(2H.1/2H.1.2/2H.1.3/2H.1.4/2H.1.5) queda documentada como cerrada:
`DirectNav2ActionBridge` está validado de forma aislada offline contra
el sandbox, su contrato de cancelación cubre la matriz pública completa
sin ninguna inferencia de terminal no observada, y no quedan brechas
conocidas en ownership terminal/cancelación/timeout/cierre degradado
dentro del alcance offline de esta serie.

### Limitaciones de esta fase

- Ningún paso de esta fase tocó hardware físico ni cambió
  `PHYSICAL_NAVIGATION` (permanece `NOT_READY`).
- `main.py`/`TourOrchestrator` no fueron modificados:
  `MAIN_RUNTIME_MIGRATED=NO`, `LEGACY_NAVIGATION_RUNTIME_ACTIVE=YES`.
- El cierre de la serie 2H.1 es exclusivamente offline; no implica que
  la navegación física esté lista ni que la Fase 2H.2 esté autorizada.

## 11. Limitaciones generales

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
- La carrera de timing transitoria bajo carga WSL (sandbox completo de
  ~18 procesos ROS) sigue siendo una característica conocida del
  entorno de desarrollo, no del código de esta fase ni de fases
  anteriores; se resuelve repitiendo la corrida, nunca modificando
  `launch/` ni `config/navigation/`.

## 12. Próximo incremento

El chat principal debe auditar el commit de la Fase 2H.1.5. Si todos
sus gates resultan aceptados, la serie 2H.1 puede considerarse cerrada
y corresponde diseñar y autorizar la **Fase 2H.2 — Main Runtime
Navigation Bridge Selection**. La validación física debe continuar
bloqueada hasta completar y auditar 2H.2, validar L2/L3 y el GO/NO-GO
del preflight dedicado. La política de misión de la Fase 2I no debe
iniciarse todavía.
