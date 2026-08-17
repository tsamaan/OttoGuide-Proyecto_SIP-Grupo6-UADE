# Main Runtime Navigation Bridge Selection — Reporte (Fase 2H.2)

> ## ⚠️ STATUS_CORRECTION / SUPERSEDED_BY_2H23 (2026-06-22)
>
> Este reporte describe la **implementación original** de la Fase 2H.2. Su
> afirmación `MAIN_RUNTIME_BRIDGE_SELECTION = READY` debe leerse con esta
> cronología corregida, no como un cierre único en la primera ejecución:
>
> - **Implementación original (2H.2)**: selector `legacy`/`direct`/`stub`,
>   interlock fail-closed, observabilidad en `/status`. Válida y conservada.
> - **Evidencia original (2H.2)**: parcial — la validación runtime end-to-end
>   contra el sandbox no se completó en la primera ejecución.
> - **Sesión de recuperación (2H.2-R)**: completó la validación runtime de los
>   cuatro escenarios de aplicación.
> - **Endurecimiento (2H.2.1, 2H.2.2)**: aislamiento de procesos, lease de
>   cleanup, identidad de kernel y escalado de señales.
> - **Corrección de evidencia (2H.2.3, este supersede)**: corrigió exit codes
>   enmascarados, clasificó el fallo de integración como
>   `FAIL_PREEXISTING_PROVEN` contra baseline `82d4942`, ejercitó por primera
>   vez en runtime la ruta de timeout del padre
>   (`parent_timeout_cleanup_executed = true`), y obtuvo estabilidad de 3
>   corridas consecutivas 4/4. Ver
>   `MAIN_RUNTIME_NAVIGATION_SELECTION_2H23_EVIDENCE_CORRECTION_REPORT.md`.
>
> Estado vigente tras 2H.2.3:
> `MAIN_RUNTIME_BRIDGE_SELECTION = READY_OFFLINE_EVIDENCE_CORRECTED_PENDING_INDEPENDENT_AUDIT`;
> `PHYSICAL_NAVIGATION = NOT_READY`.

## 1. Resumen ejecutivo

```text
MAIN_RUNTIME_BRIDGE_SELECTION = READY
DIRECT_BACKEND_INTEGRATED_OFFLINE = READY
DIRECT_BACKEND_SELECTABLE = YES

MAIN_RUNTIME_DEFAULT_BACKEND_REAL = legacy
MAIN_RUNTIME_DEFAULT_BACKEND_NON_REAL = stub

DIRECT_NAVIGATION_REAL_ENABLE_LATCH = CLOSED
LEGACY_ROLLBACK_AVAILABLE = YES

RUNTIME_VALIDATION_DIAGNOSTIC = PASS (192–195, --timeout 150)
RUNTIME_VALIDATION_RUN_1      = PASS (204–207, --timeout 150)
RUNTIME_VALIDATION_RUN_2      = PASS (216–219, --timeout 150)

L2_ODOMETRY = NOT_READY
L3_LOCALIZATION_MAP = NOT_READY
PHYSICAL_NAVIGATION = NOT_READY
PHYSICAL_READINESS_CHANGED = NO
```

`main.py` incorpora una selección explícita y fail-closed del backend de
navegación (`legacy` | `direct` | `stub`), resuelta a partir de
`NAVIGATION_BACKEND`/`ROBOT_MODE` antes de tocar hardware o ROS. El
backend directo (`DirectNav2ActionBridge`, validado de forma aislada en
toda la serie 2H.1) ahora puede inyectarse en el runtime principal contra
el sandbox offline, sin que esto cambie el comportamiento por defecto:
`ROBOT_MODE=real` sigue resolviendo a `AsyncNav2Bridge` (legacy) salvo
selección explícita, y el backend directo contra hardware real queda
bloqueado por un interlock cerrado por defecto
(`NAVIGATION_DIRECT_REAL_ENABLED=False`).

Esta fase es exclusivamente offline. No se conectó ni se ejerció ningún
comando contra el robot físico. La validación runtime completa de los
cuatro escenarios de aplicación (`boot_shutdown`, `tour_success`,
`interaction_cancel`, `emergency_cancel`) quedó bloqueada por un gap de
entorno preexistente y no relacionado (ver sección 9); todo el resto de
esta fase — código, tests, verificadores estáticos, y la infraestructura
del propio smoke test (arranque/cierre del sandbox, aislamiento por
proceso, limpieza de procesos) — está completo y verificado.

## 2. Baseline

```text
INITIAL_HEAD   = fa250ddde1de8f3a9bc9207cc6bca6341be345ca
INITIAL_PARENT = 3a7d3e29f78ef46fa66fae879affe2df9d7c78db
MENSAJE        = fix(nav): guard cancel without active goal handle
```

No se reauditó internamente `DirectNav2ActionBridge`: sus contratos de
ownership terminal, cancelación, timeouts y estado remoto desconocido
(series 2H.1/2H.1.2/2H.1.3/2H.1.4/2H.1.5) se preservan tal cual y se
verifican únicamente por regresión (tests existentes sin modificar +
guards estáticos existentes sin debilitar).

## 3. Selector de backend

`config/settings.py` agrega:

```python
NAVIGATION_BACKEND: Literal["auto", "legacy", "direct", "stub"] = "auto"
NAVIGATION_DIRECT_REAL_ENABLED: bool = False
NAVIGATION_ALLOW_STUB_TOURS: bool = False

NAVIGATION_NODE_NAME: str = "direct_nav2_action_bridge"
NAVIGATION_NAMESPACE: str = "offline_nav"
NAVIGATION_NTP_ACTION: str = "/offline_nav/navigate_to_pose"
NAVIGATION_FW_ACTION: str = "/offline_nav/follow_waypoints"
NAVIGATION_INITIAL_POSE_TOPIC: str = "/initialpose"
NAVIGATION_SERVER_TIMEOUT_S: float = 15.0
NAVIGATION_GOAL_RESPONSE_TIMEOUT_S: float = 10.0
NAVIGATION_RESULT_TIMEOUT_S: float = 120.0
NAVIGATION_CANCEL_RESPONSE_TIMEOUT_S: float = 10.0
NAVIGATION_CANCEL_TERMINAL_TIMEOUT_S: float = 15.0
```

`Settings.validate_navigation_config()` valida (antes de tocar hardware):
todos los timeouts `> 0`; `NAVIGATION_NTP_ACTION`/`NAVIGATION_FW_ACTION`
no vacíos y absolutos (`/...`); `NAVIGATION_INITIAL_POSE_TOPIC` no vacío y
absoluto; `NAVIGATION_NAMESPACE` no vacío. Cualquier violación lanza
`ValueError("NAVIGATION_CONFIG_INVALID:<detalle>")`.

## 4. Matriz de resolución

`main._resolve_navigation_backend(settings)`:

| `NAVIGATION_BACKEND` | `ROBOT_MODE` | Resultado |
| --- | --- | --- |
| `auto` | `real` | `legacy` |
| `auto` | `sim`\|`mock`\|`demo` | `stub` |
| `legacy` | cualquiera | `legacy` |
| `direct` | cualquiera | `direct` |
| `stub` | `real` | error `NAVIGATION_STUB_FORBIDDEN_IN_REAL_MODE` |
| `stub` | `sim`\|`mock`\|`demo` | `stub` |

`NAVIGATION_BACKEND=auto` (default) en `ROBOT_MODE=real` (default) resuelve
a `legacy`: el comportamiento de producción existente no cambia salvo
selección explícita.

## 5. Interlock de hardware real

`main._check_direct_real_interlock(settings, resolved_backend)`:

```text
resolved_backend == "direct"
ROBOT_MODE == "real"
NAVIGATION_DIRECT_REAL_ENABLED == False (default)
→ RuntimeError("DIRECT_NAVIGATION_REAL_MODE_NOT_AUTHORIZED")
```

Se invoca **antes** de `get_hardware_adapter()`, `hardware.initialize()` y
de cualquier construcción que pudiera iniciar ROS 2 (`rclpy.init()`,
implícito en `DirectNav2ActionBridge.start()`). Verificado por test que
ese orden se respeta incluso cuando el interlock bloquea: ni el adaptador
de hardware ni `hardware.initialize()` llegan a invocarse.

Esta fase solo autoriza la **construcción** y los **tests unitarios** de
`direct` + `real` + `NAVIGATION_DIRECT_REAL_ENABLED=True`; en ningún caso
autoriza ejecutar esa combinación contra hardware físico.

## 6. Factory fail-closed

`main._build_navigation_bridge(settings, resolved_backend)`:

- `legacy` → import lazy de `AsyncNav2Bridge`, instancia con defaults. Fallo
  de import/construcción → `RuntimeError("NAVIGATION_BACKEND_BUILD_FAILED:legacy:<detalle>")`.
- `direct` → import lazy de `DirectNav2ActionBridge`, instanciado con
  **todos** los valores `NAVIGATION_*` de `Settings` (node_name, namespace,
  ambas action names, initial pose topic, los cinco timeouts). Fallo →
  `RuntimeError("NAVIGATION_BACKEND_BUILD_FAILED:direct:<detalle>")`.
- `stub` → `_MinimalNavStub()`, sin imports de ROS.

**Sin fallback silencioso**: se eliminó por completo
`_get_nav_bridge_stub()` (el defecto literal pre-2H.2:
`except Exception: return _MinimalNavStub()`). Ninguna rama de
`_build_navigation_bridge` atrapa una excepción de un backend para
degradar a otro backend o al stub; el guard estático nuevo en
`verify_sandbox_isolation.py` rechaza explícitamente ese patrón si
reapareciera.

**Imports ROS lazy**: `rclpy` nunca se importa a nivel de módulo en
`main.py`; tampoco `AsyncNav2Bridge`/`DirectNav2ActionBridge`. Ambos
solo se importan dentro de `_build_navigation_bridge()`, y solo la rama
efectivamente seleccionada importa su clase concreta.

## 7. Orden de boot y shutdown

**Boot** (`lifespan()`):

```text
1. validate_navigation_config()
2. _resolve_navigation_backend(settings)
3. _check_direct_real_interlock(settings, resolved_backend)
4. _build_navigation_bridge(settings, resolved_backend)   — sin iniciar ROS
5. get_hardware_adapter() ; await hardware.initialize()
6. await nav_bridge.start()                                — legacy/direct inician ROS; stub es no-operativo
7. TourOrchestrator(hardware_api=hardware, nav_bridge=nav_bridge, ...)
8. app.state.orchestrator / app.state.nav_bridge = la MISMA instancia
```

Si `nav_bridge.start()` falla, se relanza como
`NAVIGATION_BACKEND_START_FAILED:<backend>:<detalle>` **antes** de crear el
orquestador: no hay `yield`, no hay `TourOrchestrator`, y el `finally`
ejecuta la secuencia de seguridad sobre el hardware ya inicializado más un
intento de `close()` sobre el bridge parcialmente construido.

**Shutdown** (`finally` del `lifespan()`, sin cambios en el orden de
seguridad ya existente):

```text
EventBus(EMERGENCY_STOP) → FSM a EMERGENCY → MotionCommand(0) → damp()
→ nav_bridge.close()
```

Un fallo en `nav_bridge.close()` nunca impide los pasos de hardware
anteriores (ya completados antes de llegar a esa línea); se registra en
`app.state.navigation_shutdown_error` (formato
`NAVIGATION_BACKEND_CLOSE_FAILED:<backend>:<detalle>`) y se loggea con
`LOGGER.critical`, nunca se silencia con un warning genérico. Errores ya
conocidos de la serie 2H.1
(`DIRECT_BRIDGE_CLOSE_REMOTE_STATE_UNKNOWN`,
`DIRECT_BRIDGE_SPIN_THREAD_STILL_ALIVE`) se propagan tal cual dentro de
ese mensaje, sin ocultarse.

## 8. Readiness y observabilidad

`api/router.py` — `_resolve_readiness_errors()` ahora bloquea
`POST /tour/start` ante:

```text
navigation backend unavailable                      (nav_bridge o backend_resolved ausentes)
navigation backend stub: autonomous tours disabled   (stub sin NAVIGATION_ALLOW_STUB_TOURS=true)
navigation backend not started                       (legacy/direct con navigation_started=False)
navigation status unavailable:<ErrorType>             (nav_bridge.get_status() lanza)
navigation remote state unknown                       (NavigationStatus.remote_state_unknown=true)
```

más la validación de hardware ya existente en `ROBOT_MODE=real`. La
verificación usa `app.state.navigation_started` (nunca solo el atributo
interno `_started` del bridge) cuando esa información explícita existe.

`GET /status` (`StatusResponse`) agrega:

```python
navigation_backend_requested: str = "unknown"
navigation_backend_resolved: str = "unknown"
navigation_started: bool = False
navigation_remote_state_unknown: bool = False
navigation_action_name: Optional[str] = None
navigation_goal_uuid: Optional[str] = None
```

construido por `_resolve_navigation_observability()`, que llama a
`nav_bridge.get_status()`; si falla, no rompe el endpoint — usa valores
conservadores (`remote_state_unknown=True`, nombres en `None`) y deja que
el fallo real se refleje por separado en `readiness_errors`. Nunca expone
objetos ROS ni el handle interno del bridge.

## 9. Tests, verificadores y diagnóstico runtime

### 9.1 Tests unitarios

`tests/unit/test_navigation_runtime_selection.py` (nuevo, 41 tests):
resolución de backend (7 casos de la matriz), interlock real (4 casos),
factory fail-closed (6 casos, incluyendo import-failure sin fallback),
validación de config (7 casos), orden fail-closed antes de hardware (1
caso dedicado), lifespan completo (4 casos: éxito con backend `direct`,
fallo de `start()`, fallo de `close()`, backend `stub` no marca
`navigation_started`), readiness (7 casos), observabilidad de
`StatusResponse` (3 casos). Nunca depende de ROS real:
`AsyncNav2Bridge`/`DirectNav2ActionBridge` se construyen sin iniciar
`rclpy` (solo en `__init__`); `main.py` se importa con mocks mínimos de
los tres paquetes preexistentes y no relacionados que faltan en este
workstation (`pyttsx3`/`speech_recognition`/`aiohttp`, mismo gap ya
documentado en `test_architecture_reconciliation_contract.py`). El propio
archivo se auto-protege con `@unittest.skipUnless` si
`pydantic_settings`/`fastapi` no están instalados en el entorno que lo
ejecuta (ver 9.4).

`tests/unit/test_architecture_reconciliation_contract.py` y
`tests/unit/test_offline_navigation_sandbox_isolation.py`: sin
regresiones (360 passed + 48 skipped en Windows, 384 tests OK en WSL).

### 9.2 Guards estáticos nuevos

`tools/hil/offline_navigation/verify_sandbox_isolation.py` agrega:

- `check_navigation_backend_selector_contract`: exige el selector
  `Literal["auto", "legacy", "direct", "stub"]` explícito y los dos
  interlocks (`NAVIGATION_DIRECT_REAL_ENABLED`/`NAVIGATION_ALLOW_STUB_TOURS`)
  cerrados por defecto en `config/settings.py`.
- `check_main_runtime_navigation_selection_contract`: exige las tres
  funciones (`_resolve_navigation_backend`, `_check_direct_real_interlock`,
  `_build_navigation_bridge`) presentes; la matriz auto-real/auto-stub y
  el rechazo de stub-en-real dentro de la primera; el error de interlock y
  la lectura del latch dentro de la segunda; el error
  `NAVIGATION_BACKEND_BUILD_FAILED` y los diez kwargs `settings.*` del
  bridge directo dentro de la tercera; rechaza por AST cualquier
  `except Exception` dentro de la factory que construya
  `_MinimalNavStub()` (el defecto literal pre-2H.2); rechaza imports de
  `rclpy`/`AsyncNav2Bridge`/`DirectNav2ActionBridge` a nivel de módulo; y
  rechaza la presencia literal de `/cmd_vel` en `main.py`.

9 tests nuevos en `test_offline_navigation_sandbox_isolation.py` cubren
ambos guards, incluyendo la reproducción exacta del defecto rechazado.

### 9.3 Smoke test de integración de aplicación

`tools/hil/offline_navigation/smoke_test_main_runtime_navigation_selection.py`
(nuevo): mismo patrón de aislamiento por proceso ya aceptado (un proceso
hijo por escenario, un `ROS_DOMAIN_ID` cada uno, salida JSON única
validada por identidad/exit-code, logs propios bajo `/tmp`, cleanup
dirigido al PGID propio). CLI pública: `--base-domain-id`, `--timeout`,
`--output`; interna: `--scenario`
(`boot_shutdown`/`tour_success`/`interaction_cancel`/`emergency_cancel`).
Cada hijo levanta el sandbox offline completo (incluyendo
`waypoint_follower`, necesario porque `ROBOT_MODE=mock` hace que
`TourOrchestrator._navigation_loop` use `navigate_to_waypoints` →
`FollowWaypoints`), luego entra a `main.lifespan(app)` como gestor de
contexto async sobre un `app` mínimo (solo `.state`) — sin Uvicorn, sin
sockets — con `NAVIGATION_BACKEND=direct` y
`NAVIGATION_DIRECT_REAL_ENABLED=false`, y ejerce siempre al
`TourOrchestrator` real (`dispatch_tour`/`request_interaction`/
`emergency_stop`), nunca al bridge directamente. El hardware se inyecta
como `_RecordingMockHardware` (envuelve `hardware.mock_adapter.MockHardwareAPI`
real, registrando cada `move()`/`damp()`) para poder afirmar
`MotionCommand(0)`/`damp()` observados sin inventar un HAL paralelo.

### 9.4 Diagnóstico runtime y corridas oficiales (sesión de recuperación 2H.2-R, 2026-06-22)

```text
DIAGNOSTIC_RESULT = PASS (base-domain-id 192–195, --timeout 150)
RUN_1             = PASS (base-domain-id 204–207, --timeout 150)
RUN_2             = PASS (base-domain-id 216–219, --timeout 150)
```

La versión original de este documento registraba `DIAGNOSTIC_RESULT = BLOCKED` /
`RUN_1 = NOT_EXECUTED` / `RUN_2 = NOT_EXECUTED`. El bloqueo tenía dos
causas raíz independientes que se corrigieron en la sesión de
recuperación:

**Causa 1 — imports a nivel de módulo en `main.py`** (hereditario, anterior a
esta fase):
`import uvicorn`, las importaciones de `fastapi` y `api.router`, las de
`config.settings`, `src.core.*`, y la instanciación del singleton
`MISSION_AUDIT_LOGGER = MissionAuditLogger()` se ejecutaban en tiempo de
importación de `main.py`, antes de que cualquier función entrara en
acción. El smoke test solo necesita entrar a `lifespan(app)`, pero
`import main` ya disparaba todos esos imports. Ninguno de esos paquetes
estaba presente en el entorno ROS de WSL.

Corrección: todos los imports no-stdlib se hicieron lazy (dentro de las
funciones que los necesitan); el singleton se instancia dentro de
`lifespan()`. Único import que permanece a nivel de módulo:
`from hardware.interface import RobotHardwareInterface`. Se agregaron
wrappers `get_settings()` y `get_hardware_adapter()` con atributo
`cache_clear` para mantener el patcheo de tests sin perder la
inyectabilidad.

Los paquetes faltantes se instalaron en el site-packages de usuario de
WSL (`--user --break-system-packages`):
`uvicorn==0.37.0`, `fastapi==0.118.2`, `python-statemachine==3.0.0`,
`pydantic-settings==2.13.1`, `pydantic==2.12.0`, `httpx==0.28.1`.

**Causa 2 — `python-statemachine` 3.0.0 + `AsyncEngine`** (comportamiento de
metaclase no documentado):
`TourOrchestrator` usa `Meta.engine = AsyncEngine`. En
`python-statemachine==3.0.0`, llamar `super().__init__()` dentro de un
`__init__` síncrono cuando hay un event loop activo **no** entra
automáticamente al estado inicial; `state_id` devuelve `"uninitialized"`
hasta que se invoca `await sm.activate_initial_state()` de forma
explícita. Todos los escenarios de smoke que despachaban tours fallaban
con `FSM_NOT_IDLE_BEFORE_DISPATCH:uninitialized`.

Corrección: se agregó `await orchestrator.activate_initial_state()` en
`main.lifespan()` inmediatamente después de construir el
`TourOrchestrator`. Ningún archivo frozen fue tocado.

**Correcciones asociadas en tests y smoke**:
- `test_navigation_runtime_selection.py`: removido `@unittest.skipUnless`
  de `BackendResolutionTests` y `DirectRealInterlockTests` (usan
  `SimpleNamespace`, no `Settings`); corregido `self.main.OttoEventBus`
  en `FailClosedOrderTests`/`LifespanDirectBackendTests` — tras hacer
  `OttoEventBus` lazy en `_run_shutdown_sequence`, ya no es atributo del
  módulo; ahora se importa directamente desde `src.core.event_bus` en
  setUp/tearDown.
- `smoke_test_main_runtime_navigation_selection.py`: mismo fix para
  `main_module.OttoEventBus.reset_for_testing()`; `get_settings.cache_clear()`
  preservado via el wrapper de módulo.

**Resultados de tests unitarios y guards**: sin cambios en los totales
(41/41 tests nuevos + 9 guards estáticos PASS en Windows y WSL).

**Nota de timing**: las corridas diagnóstica y oficiales requirieron
`--timeout 150` (en lugar del default 120). Con 120s, los escenarios 3 y
4 (domains 194/195) fallaban con `bt_navigator_NOT_ACTIVE` y
`waypoint_follower_NOT_DISCOVERED` — una carrera de timing del lifecycle
manager bajo carga WSL, igual a la documentada en el runbook para otros
componentes. Con 150s, todas las corridas resultaron limpias. No se
realizaron cambios de código para resolver esto.

**Resultados por escenario**:

| Escenario | Diag (192–195) | Run 1 (204–207) | Run 2 (216–219) |
|---|---|---|---|
| `boot_shutdown` | PASS | PASS | PASS |
| `tour_success` | PASS | PASS | PASS |
| `interaction_cancel` | PASS | PASS | PASS |
| `emergency_cancel` | PASS | PASS | PASS |

Métricas representativas (Run 1):
- `tour_success`: `final_fsm_state: idle`, `last_result_status: SUCCEEDED`,
  `remote_state_unknown: false`.
- `interaction_cancel`: `cancel_accepted: true`,
  `cancel_terminal_status: CANCELED`, `mission_resume_policy: DEFERRED_2I`.
- `emergency_cancel`: `final_fsm_state: emergency`, `damp_calls: 1`,
  `cancel_terminal_status: CANCELED`.

## 10. Interacción y emergencia (código preparado, no ejecutado)

`_run_interaction_cancel`/`_run_emergency_cancel` (en el smoke test)
despachan un tour de un único waypoint lejano (`1.5m`) vía
`TourOrchestrator.dispatch_tour()`, esperan `nav_bridge.get_status()`
hasta `task_active=True` con `feedback_count>0`, y entonces invocan
`orchestrator.request_interaction(...)`/`orchestrator.emergency_stop(...)`
respectivamente — nunca el bridge directamente. Exigen
`cancel_requested`/`cancel_accepted=true`, terminal `CANCELED`,
`remote_state_unknown=false`, ausencia de goal activo tras la
cancelación, y al menos un `MotionCommand(0)` real observado en
`_RecordingMockHardware.move_calls` (más `damp()` observado para
emergencia). No exigen que la misión se reanude ni se complete:

```text
MISSION_RESUME_POLICY = DEFERRED_2I
```

Esta lógica fue validada en las dos corridas oficiales (dominios 206/207 y
218/219). Los escenarios `interaction_cancel` y `emergency_cancel`
produjeron `cancel_accepted: true`, terminal `CANCELED`,
`remote_state_unknown: false`, `task_active_after: false`, y al menos un
`MotionCommand(0)` real en `_RecordingMockHardware.move_calls` (más
`damp_calls: 1` para emergencia). Ver sección 9.4.

## 11. Rollback

Configuración (sin tocar código):

```text
NAVIGATION_BACKEND=legacy
```

equivalente al comportamiento previo a esta fase. También:

```text
NAVIGATION_BACKEND=auto
ROBOT_MODE=real
→ legacy
```

(el default histórico no cambia). Git:

```text
git revert <SHA_DE_2H_2>
```

No se ejecuta porque la fase, dentro de su alcance offline alcanzable, se
considera aceptable (ver sección 12).

## 12. Limitaciones

- `MAIN_RUNTIME_MIGRATED` sigue siendo `NO` en el sentido de "comportamiento
  por defecto cambiado": `ROBOT_MODE=real` continúa resolviendo a
  `AsyncNav2Bridge` salvo selección explícita de `NAVIGATION_BACKEND=direct`.
  Lo que esta fase agrega es la **capacidad** de seleccionar el backend
  directo en el runtime principal, no un cambio de default.
- El bridge directo contra hardware real permanece bloqueado por el
  interlock `NAVIGATION_DIRECT_REAL_ENABLED` (cerrado por defecto); nunca
  se afirma que el bridge directo fue validado con ROS 2 Foxy ni con
  hardware real.
- La validación runtime completa de `main.py`/`TourOrchestrator` contra
  el sandbox (los cuatro escenarios de aplicación) está **COMPLETA**: ver
  sección 9.4 (sesión de recuperación 2H.2-R, 2026-06-22).
- `L2_ODOMETRY`, `L3_LOCALIZATION_MAP` y `PHYSICAL_NAVIGATION` permanecen
  `NOT_READY`, sin cambios.
- No se utilizó hardware físico en ningún paso de esta fase.
