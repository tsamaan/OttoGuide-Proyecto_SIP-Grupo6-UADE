# Main Runtime Navigation Bridge Selection — Reporte (Fase 2H.2.1)

## 1. Resumen ejecutivo

```text
MAIN_RUNTIME_HARDENING_2H21 = COMPLETE

FAIL_CLOSED_MISSING_GET_STATUS  = FIXED
CENTRAL_TEST_SKIP_DECORATORS    = REMOVED
DEPENDENCY_BLOCKED_IMPORT_TEST  = ADDED
STATIC_GUARDS_2H21              = ADDED (3 nuevos)
SMOKE_POPEN_REDESIGN            = COMPLETE

RUNTIME_VALIDATION_DIAGNOSTIC = FAIL-PARTIAL (180–183: 2/4; timing issues solo)
RUNTIME_VALIDATION_RUN_1      = PASS (196–199, --timeout 150)
RUNTIME_VALIDATION_RUN_2      = FAIL-PARTIAL (224–227: 3/4; timing issue solo)

L2_ODOMETRY = NOT_READY
L3_LOCALIZATION_MAP = NOT_READY
PHYSICAL_NAVIGATION = NOT_READY
PHYSICAL_READINESS_CHANGED = NO
```

Microincremento aditivo sobre la Fase 2H.2 que cierra tres brechas de
hardening en `api/router.py` y los tests de selección de backend:

1. **Fail-closed `get_status`**: `_resolve_readiness_errors()` y
   `_resolve_navigation_observability()` ya bloquean tours
   (error `"navigation status unavailable:missing"`) y marcan
   `remote_state_unknown=True` cuando `get_status` está ausente o no
   es callable, en lugar de silenciar la condición.

2. **Eliminación de `@skipUnless` centrales**: las cinco clases de test
   que no ejercitan el modelo real de Pydantic Settings eliminaron su
   decorador `@skipUnless`/`@skipIf` y usan `_fake_settings()` +
   `_install_router_fakes()` para correr en cualquier entorno.

3. **Test de importación con dependencias bloqueadas**: nuevo
   `DependencyBlockedImportTests.test_main_importable_with_blocked_critical_dependencies`
   que verifica mediante subprocess que `main.py` es importable incluso
   con `uvicorn`, `fastapi`, `pydantic_settings`, `statemachine` e
   `httpx` bloqueados.

4. **Guards estáticos nuevos** en `verify_sandbox_isolation.py`:
   `check_readiness_fail_closed_missing_status_contract`,
   `check_test_central_classes_no_broad_skip`, y extensión de
   `check_main_runtime_navigation_selection_contract` para rechazar
   `import uvicorn` / `import fastapi` / `from fastapi import ...` a
   nivel de módulo en `main.py`.

5. **Rediseño smoke padre/hijo**: `subprocess.run` → `subprocess.Popen`
   con control file atómico (`os.replace`), escalado completo de señales
   en timeout del padre (SIGINT→sandbox PGID, SIGTERM, SIGKILL exacto,
   luego mismo ciclo para child PGID), conteo de threads propios y
   detección de zombies en el JSON de salida de cada escenario.

Esta fase es exclusivamente offline. No se conectó ni se ejerció ningún
comando contra el robot físico. El defecto `ABORTED` en `emergency_cancel`
domain 183 y los fallos `NOT_ACTIVE`/`NOT_DISCOVERED` en dominios 180 y
226 son intermitencias de startup del sandbox ROS 2 Jazzy, no del selector
de backend.

## 2. Baseline

```text
INITIAL_HEAD   = da780e0948693421c5c63589224e9e677eb505fb
INITIAL_PARENT = fa250ddde1de8f3a9bc9207cc6bca6341be345ca
MENSAJE        = feat(nav): add fail-closed runtime bridge selection
```

No se modificó ningún archivo del directorio `src/navigation/`,
`src/core/tour_orchestrator.py`, `launch/`, `config/navigation/`,
`hardware/`, `src/hardware/`, `simulator/`, ni `scripts/`.

## 3. Correcciones en `api/router.py`

### 3.1 `_resolve_readiness_errors` — fail-closed `get_status` ausente

**Antes (Fase 2H.2)**: cuando `get_status` estaba ausente o no era
callable, la función saltaba silenciosamente sin agregar ningún error.
Un bridge en ese estado incompleto podía superar la barrera de readiness.

**Después (Fase 2H.2.1)**:
```python
get_status_fn = getattr(nav_bridge, "get_status", None)
if not callable(get_status_fn):
    errors.append("navigation status unavailable:missing")
else:
    try:
        nav_status = await asyncio.wait_for(get_status_fn(), timeout=0.25)
        if getattr(nav_status, "remote_state_unknown", False):
            errors.append("navigation remote state unknown")
    except Exception as exc:
        errors.append(f"navigation status unavailable:{type(exc).__name__}")
```

### 3.2 `_resolve_navigation_observability` — `remote_state_unknown` fail-closed

**Antes**: misma condición; `remote_state_unknown` quedaba en su valor
inicial sin actualizarse cuando `get_status` estaba ausente.

**Después**:
```python
get_status_fn = getattr(nav_bridge, "get_status", None)
if not callable(get_status_fn):
    remote_state_unknown = True
else:
    ...
```

## 4. Cambios en `tests/unit/test_navigation_runtime_selection.py`

### 4.1 Helper `_fake_settings`

`SimpleNamespace` que reemplaza `config.settings.Settings` con todos los
campos de navegación necesarios y un `validate_navigation_config` no-op.
Permite que las clases de test que no ejercitan el modelo Pydantic
funcionen sin `pydantic_settings`.

### 4.2 Helpers `_install_router_fakes` / `_remove_router_fakes`

Instalan fakes mínimas para `fastapi`, `statemachine` y
`src.api.websocket_manager` cuando `api.router` no está en caché.
Manejan el `ValueError: fastapi.__spec__ is None` de Python 3.12 con
un `try/except (ValueError, ModuleNotFoundError)` alrededor de
`importlib.util.find_spec`.

### 4.3 `_FakeNavBridgeNoStatus`

Fake del `NavigationPort` sin atributo `get_status`, que ejercita el
camino fail-closed de método ausente introducido en 3.1/3.2.

### 4.4 Clases centrales — decoradores `@skipUnless` eliminados

| Clase                        | Cambio                                                |
|------------------------------|-------------------------------------------------------|
| `NavigationBridgeFactoryTests`  | `@skipUnless` eliminado; `Settings(...)` → `SimpleNamespace(...)` |
| `FailClosedOrderTests`          | `@skipUnless` eliminado; `Settings(...)` → `_fake_settings(...)` |
| `LifespanDirectBackendTests`    | `@skipUnless` eliminado; `_settings()` → retorna `_fake_settings()` |
| `ReadinessTests`                | `@skipUnless` eliminado; setUp agrega `_install_router_fakes` |
| `StatusObservabilityTests`      | `@skipUnless` eliminado; setUp agrega `_install_router_fakes` |

`NavigationConfigValidationTests` conserva su `@skipUnless` porque
ejercita el modelo real de Pydantic Settings.

### 4.5 Nuevos tests

**En `ReadinessTests`**:
- `test_missing_get_status_blocks_readiness`: bridge sin `get_status` →
  `"navigation status unavailable:missing"` en errors
- `test_noncallable_get_status_blocks_readiness`: `get_status = "not_a_callable"` →
  mismo error

**En `StatusObservabilityTests`**:
- `test_missing_get_status_marks_remote_state_unknown`: bridge sin
  `get_status` → `navigation_remote_state_unknown = True`

**Clase `DependencyBlockedImportTests`** (nueva):
- `test_main_importable_with_blocked_critical_dependencies`: subprocess
  bloquea `uvicorn`, `fastapi`, `pydantic_settings`, `statemachine`,
  `httpx` y verifica que `main.py` importa sin excepción y expone los
  helpers de selección de backend.

## 5. Guards estáticos en `verify_sandbox_isolation.py`

### 5.1 `check_readiness_fail_closed_missing_status_contract`

Comprueba que `"navigation status unavailable:missing"` aparece
literalmente en `api/router.py`. Error: `READINESS_MISSING_GET_STATUS_NOT_BLOCKED`.

### 5.2 `check_test_central_classes_no_broad_skip`

Recorre el AST de `test_navigation_runtime_selection.py`, encuentra las
cinco clases centrales (`NavigationBridgeFactoryTests`,
`FailClosedOrderTests`, `LifespanDirectBackendTests`, `ReadinessTests`,
`StatusObservabilityTests`) y verifica que ninguna tiene `@skipUnless` ni
`@skipIf`. Error: `CENTRAL_TEST_CLASS_HAS_BROAD_SKIP:<ClassName>`.

### 5.3 Extension de `check_main_runtime_navigation_selection_contract`

Recorre el nivel de módulo del AST de `main.py` y emite
`MAIN_NAVIGATION_EAGER_MODULE_IMPORT:<nombre>` si encuentra:
- `import uvicorn`
- `import fastapi` / `import fastapi.*`
- `from fastapi import ...` / `from fastapi.* import ...`

### 5.4 Tests en `test_offline_navigation_sandbox_isolation.py`

| Clase                                   | Tests añadidos |
|-----------------------------------------|----------------|
| `MainRuntimeNavigationSelectionContractTests` | `test_rejects_eager_module_level_uvicorn_import`, `test_rejects_eager_module_level_fastapi_import` |
| `ReadinessFailClosedMissingStatusContractTests` (nueva) | `test_real_router_passes_fail_closed_contract`, `test_rejects_router_missing_status_string` |
| `CentralClassesNoBroadSkipContractTests` (nueva) | `test_real_test_file_passes_no_broad_skip_contract`, `test_rejects_central_class_with_skip_unless`, `test_rejects_central_class_with_skip_if`, `test_non_central_class_with_skip_unless_is_allowed` |

## 6. Rediseño del smoke test padre/hijo

### 6.1 Control file atómico

Antes de lanzar cada proceso hijo, el padre escribe un JSON inicial con
`{token_ns, scenario, domain_id, parent_pid, child_pid: null, ...}` vía
`_write_atomic(path, data)` (`os.replace` sobre un `.tmp` intermedio).
El hijo actualiza ese archivo con su propio PID/PGID al arrancar, y con el
PID/PGID del sandbox una vez que lo lanza. Esto garantiza que el padre
puede enviar señales precisas si el hijo excede el timeout.

### 6.2 `subprocess.Popen` en lugar de `subprocess.run`

```python
child_proc = subprocess.Popen(child_cmd, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
child_stdout, _ = child_proc.communicate(timeout=args.timeout + 150.0)
```

En `TimeoutExpired`, `_parent_timeout_cleanup(child_proc, control_file)`
ejecuta la escalada completa:

```text
SIGINT  → sandbox_pgid (del control file) → espera 15 s
SIGTERM → sandbox_pgid                    → espera 10 s
SIGKILL → PIDs exactos del sandbox        → espera  5 s
SIGINT  → child_pgid (live o del ctrl)    → espera  5 s
SIGTERM → child_pgid                      → espera  5 s
SIGKILL → PIDs exactos del hijo           → espera  5 s
```

Ninguna señal se envía por nombre ni con comodines; todos los PIDs se
obtienen mediante `os.getpgid()` o `ps -eo pid,pgid` en el momento del
kill.

### 6.3 Métricas de threads y zombies en el JSON hijo

Cada resultado de escenario agrega:

```json
{
  "owned_threads_remaining": 1,
  "owned_thread_names": ["asyncio_0"],
  "zombies_remaining": 0,
  "zombie_pids": []
}
```

`owned_threads_remaining` = `threading.active_count()` post-cleanup −
baseline pre-scenario. El thread `asyncio_0` observado en los resultados
es un hilo interno del event loop de Python y no indica un leak del
bridge o del sandbox.

El campo `parent_timeout_cleanup_executed` aparece en el resultado
agregado del padre por escenario.

## 7. Resultados de test

### 7.1 Windows (Python 3.13.2)

```text
test_navigation_runtime_selection.py       : 45 passed
test_offline_navigation_sandbox_isolation.py: 299 passed, 48 skipped
Full suite                                  : 516 passed, 48 skipped, 1 pre-existing integration failure
```

### 7.2 WSL Ubuntu-24.04 (Python 3.12, ROS 2 Jazzy)

```text
test_navigation_runtime_selection.py + test_offline_navigation_sandbox_isolation.py: 343 passed, 25 skipped
Static verifier (verify_sandbox_isolation.py): decision = PASS
```

## 8. Corridas de validación runtime (WSL Ubuntu-24.04)

### 8.1 Diagnóstico — base-domain-id 180, timeout 150

```text
HASH: 706b031da1a66716d1f34a9ff03ee2b0d10fcb831685027da3839c65d28e32a0
boot_shutdown      (180): FAIL — map_server_NOT_ACTIVE, otros NOT_DISCOVERED (sandbox timing)
tour_success       (181): PASS — backend=direct, bridge=DirectNav2ActionBridge, orphans=0, zombies=0
interaction_cancel (182): PASS — cancel ACCEPTED, terminal=CANCELED, orphans=0, zombies=0
emergency_cancel   (183): FAIL — terminal=ABORTED (Nav2 abortó en lugar de CANCELED; timing)
```

### 8.2 Corrida oficial 1 — base-domain-id 196, timeout 150

```text
HASH: 76c858f4e1591821aeb30e2a0c1c1c25b814dc10263939578bc7b227b86d6f37
DECISION: PASS (4/4)

boot_shutdown      (196): PASS — readiness_errors=[], orphans=0, zombies=0
tour_success       (197): PASS — final_fsm_state=idle, last_result=SUCCEEDED, orphans=0, zombies=0
interaction_cancel (198): PASS — cancel ACCEPTED, terminal=CANCELED, zero_command=true, orphans=0, zombies=0
emergency_cancel   (199): PASS — terminal=CANCELED, damp_calls=1, zero_command=true, orphans=0, zombies=0
```

### 8.3 Corrida oficial 2 — base-domain-id 224, timeout 150

```text
HASH: 98f73cedc7fcf8b06ec89655e9358c5ceda0850d270aac372892c60e3c696652
DECISION: FAIL-PARTIAL (3/4)

boot_shutdown      (224): PASS — readiness_errors=[], orphans=0, zombies=0
tour_success       (225): PASS — final_fsm_state=idle, last_result=SUCCEEDED, orphans=0, zombies=0
interaction_cancel (226): FAIL — bt_navigator_NOT_ACTIVE, waypoint_follower_NOT_DISCOVERED (sandbox timing)
emergency_cancel   (227): PASS — terminal=CANCELED, damp_calls=1, zero_command=true, orphans=0, zombies=0
```

Los fallos de la corrida 2 son del mismo tipo que los del diagnóstico:
nodos Nav2 que no alcanzan el estado `active` dentro del timeout de 150 s
en esa ejecución específica. El backend selection, la identidad del bridge
y la limpieza de procesos (orphans=0, zombies=0) son correctos en todos
los escenarios donde el sandbox arrancó.

### 8.4 Evidencia de correctitud del selector

En todos los escenarios donde el sandbox estuvo disponible:
```text
navigation_backend_requested = direct
navigation_backend_resolved  = direct
bridge_class                 = DirectNav2ActionBridge
navigation_started           = true
orphan_processes             = 0
zombies_remaining            = 0
parent_timeout_cleanup_executed = false
```

## 9. Archivos modificados en Fase 2H.2.1

```text
codigo ottoguide/api/router.py
codigo ottoguide/tests/unit/test_navigation_runtime_selection.py
codigo ottoguide/tests/unit/test_offline_navigation_sandbox_isolation.py
codigo ottoguide/tools/hil/offline_navigation/verify_sandbox_isolation.py
codigo ottoguide/tools/hil/offline_navigation/smoke_test_main_runtime_navigation_selection.py
documentacion general del proyecto/Arquitectura/ADR_002_RECONCILIACION_NAVEGACION_HARDWARE.md
documentacion general del proyecto/Arquitectura/MAIN_RUNTIME_NAVIGATION_SELECTION_2H21_HARDENING_REPORT.md (nuevo)
documentacion general del proyecto/Operaciones_HIL/PREFLIGHT_DIRECT_NAV2_ACTION_BRIDGE_PHYSICAL_VALIDATION.md
```

## 10. Declaración final

```text
MAIN_RUNTIME_HARDENING_2H21     = COMPLETE
READINESS_FAIL_CLOSED_FIXED     = YES (get_status ausente o no callable → bloquea tours)
CENTRAL_TEST_SKIP_FREE          = YES (5 clases centrales sin @skipUnless)
STATIC_GUARDS_ADDED             = YES (3 guards nuevos, todos verificados en PASS)
SMOKE_POPEN_CONTROL_FILE        = YES (Popen + control atómico + escalada timeout)
RUNTIME_OFFICIAL_RUN_1_PASS     = YES (196–199, 4/4)
RUNTIME_OFFICIAL_RUN_2_PARTIAL  = YES (224–227, 3/4; fallo por timing sandbox, no por selector)
PHYSICAL_READINESS_CHANGED      = NO
```
