# Architecture Reconciliation Report — Fase 2H.0

**Fecha**: 2026-06-21
**Rama**: `robot`
**Baseline inicial**: `3b37e36a65aaab8f015e4ed978c9ebef8bf8b732` (`feat(nav): add isolated waypoint follower`)

## 1. Objetivo

Reconciliar los contratos de navegación y hardware utilizados por el
runtime de OttoGuide sin cambiar el comportamiento funcional de
navegación. Separar contratos puros de dominio de implementaciones
ROS 2/BasicNavigator/SDK Unitree. Ver decisión completa en
[ADR_002_RECONCILIACION_NAVEGACION_HARDWARE.md](ADR_002_RECONCILIACION_NAVEGACION_HARDWARE.md).

## 2. Baseline

```text
INITIAL_BRANCH=robot
INITIAL_HEAD=3b37e36a65aaab8f015e4ed978c9ebef8bf8b732
INITIAL_PARENT=6fa9f8907bbe22b81ee8674b9c6f3a1f42a805b9
INITIAL_COMMIT_MESSAGE=feat(nav): add isolated waypoint follower
INITIAL_WORKTREE=clean
```

## 3. Inventario de imports (antes de los cambios)

- `src/core/tour_orchestrator.py` importaba `src.hardware.RobotHardwareAPI`,
  `src.hardware.RobotHardwareAPIError`, `src.hardware.interface.MotionCommand`,
  y `src.navigation.AsyncNav2Bridge`/`NavWaypoint`.
- `src/navigation/nav2_bridge.py` definía `NavWaypoint`/`NavigationStatus`
  directamente (sin módulo `models.py` separado), junto con `AsyncNav2Bridge`
  (envoltorio de `BasicNavigator`).
- `src/navigation/__init__.py` mapeaba `NavWaypoint`/`NavigationStatus` a
  `.nav2_bridge` exclusivamente.
- No existía `src/navigation/port.py` ni ningún contrato `Protocol` para
  navegación.
- `main.py` ya importaba `hardware.interface.RobotHardwareInterface`
  (HAL canónica desde fases previas) y `config.settings.get_hardware_adapter()`
  ya resolvía exclusivamente contra `hardware.real_adapter`/`hardware.sim_adapter`/
  `hardware.mock_adapter` — ningún cambio fue necesario en `settings.py` ni en
  los adaptadores.
- `tests/integration/test_tour_orchestrator.py` usaba `src.hardware.RobotHardwareAPI`
  con un patrón singleton (`get_instance`/`_instance`) y `MockHighLevelClient`,
  no reflejando el wiring real de `main.py` (que usa `hardware.mock_adapter.MockHardwareAPI`
  directamente, sin singleton).
- `tests/mocks/mock_nav2_bridge.py` (`MockNav2Bridge`) no exponía `send_goal`
  ni `is_navigation_active`.

## 4. Diagrama textual — antes

```text
main.py
 ├─ get_hardware_adapter() → hardware/*
 └─ TourOrchestrator
     ├─ type/import hardware → src.hardware.RobotHardwareAPI
     └─ navigation → AsyncNav2Bridge
                      ├─ BasicNavigator
                      ├─ /cmd_vel
                      └─ /cmd_vel_nav
```

## 5. Diagrama textual — después

```text
main.py
 ├─ RobotHardwareInterface → hardware/*
 └─ TourOrchestrator
     ├─ RobotHardwareInterface (hardware.interface)
     └─ NavigationPort (src.navigation.port)
          ├─ legacy (inyectada en runtime): AsyncNav2Bridge
          │                                  ├─ BasicNavigator
          │                                  ├─ /cmd_vel
          │                                  └─ /cmd_vel_nav
          └─ futuro 2H.1: DirectNav2ActionBridge
                           ├─ /offline_nav/navigate_to_pose
                           └─ /offline_nav/follow_waypoints
```

## 6. Contradicciones encontradas

1. `tests/integration/test_tour_orchestrator.py` usaba un patrón singleton
   (`RobotHardwareAPI.get_instance()`/`_instance = None`) y un cliente SDK
   mock (`MockHighLevelClient`) que no corresponden al wiring real de
   `main.py`, el cual instancia `hardware.mock_adapter.MockHardwareAPI()`
   directamente, sin singleton ni cliente SDK simulado de bajo nivel. El
   test pasaba contra una arquitectura distinta a la realmente desplegada.
2. El docstring del módulo `smoke_test_offline_waypoint_follower.py` (heredado
   de la Fase 2G) describía el escenario UNREACHABLE como "real occupied
   cell ... confirmed via direct inspection of the .pgm pixel data", una
   descripción que la propia Fase 2G había descartado y corregido en el
   comentario de código adyacente, pero que nunca se actualizó en el
   docstring del módulo.
3. `tests/integration/test_tour_orchestrator.py` y `tests/integration/test_api_server.py`
   ya fallaban en la recolección de pytest en este workstation **antes** de
   cualquier cambio de esta fase, por una cadena de dependencias ausentes
   en el `.venv` de Windows (`pyttsx3`, y más profundamente `speech_recognition`
   y `aiohttp`, todos transitivos vía `src.interaction`). Documentado en la
   sección 11 (Limitaciones).

## 7. Cambios realizados

### 7.1 Modelos puros (`src/navigation/models.py`, nuevo)

`NavWaypoint` (frozen, slots) y `NavigationStatus` (slots) movidos sin
cambios de campos/semántica desde `nav2_bridge.py`. Cero imports de
`rclpy`/`cv2`/`nav2_simple_commander`. Verificado con `compile()` puro y
con import real en subprocess aislado (Windows y WSL Jazzy).

### 7.2 Contrato `NavigationPort` (`src/navigation/port.py`, nuevo)

`Protocol` `runtime_checkable` con 7 métodos async:
`start`, `close`, `navigate_to_waypoints`, `send_goal`, `cancel_navigation`,
`inject_absolute_pose`, `is_navigation_active`. Sin implementación, sin
imports de ROS. `PoseEstimate` se importa solo bajo `TYPE_CHECKING`.

### 7.3 `src/navigation/nav2_bridge.py` (modificado)

Las definiciones de `NavWaypoint`/`NavigationStatus` se eliminaron y se
reemplazaron por `from src.navigation.models import NavWaypoint, NavigationStatus`.
Ningún otro comportamiento del bridge cambió: `BasicNavigator`, `/cmd_vel`,
`/cmd_vel_nav`, `ThreadPoolExecutor`, `MultiThreadedExecutor` permanecen
intactos.

### 7.4 `src/navigation/__init__.py` (modificado)

`NavWaypoint`/`NavigationStatus` ahora mapean a `.models`; se agregó
`NavigationPort` mapeado a `.port`. Lazy imports preservados
(`__getattr__`/`__dir__`).

### 7.5 `src/core/tour_orchestrator.py` (modificado)

- Import `from src.hardware import RobotHardwareAPI, RobotHardwareAPIError`
  reemplazado por `from hardware.interface import MotionCommand, RobotHardwareInterface`.
- Import `from src.navigation import AsyncNav2Bridge, NavWaypoint` reemplazado
  por `from src.navigation.models import NavWaypoint` + `from src.navigation.port import NavigationPort`.
- Constructor: `hardware_api: RobotHardwareInterface`, `nav_bridge: NavigationPort`.
- Atributos de instancia retipados igual.
- `except RobotHardwareAPIError as exc:` eliminado de `on_enter_emergency`;
  el `except Exception as exc:` ya existente preserva la misma contención
  funcional (Damp() sigue ejecutándose; el log crítico solo pierde el tipo
  específico de excepción en el mensaje, no la cobertura).
- Ningún estado, transición, timeout, orden de emergencia, política de
  waypoints, auditoría, telemetría o llamada a `move(0)`/`damp()` cambió.

### 7.6 `main.py` (modificado)

- Docstring actualizado para documentar `hardware/` como HAL canónica,
  `src/hardware/` como legacy en cuarentena, y `NavigationPort` como
  contrato de navegación.
- `_MinimalNavStub` recibió dos métodos nuevos: `send_goal()` (retorna
  `False`) y `is_navigation_active()` (retorna `False`), completando la
  conformidad estructural con `NavigationPort` (verificado vía AST: los 7
  métodos están presentes).
- Lifespan, factory de hardware, orden de shutdown, inicialización de
  `AsyncNav2Bridge` en modo real, endpoints, FastAPI, Uvicorn, señales y
  timeouts: sin cambios.

### 7.7 `tests/mocks/mock_nav2_bridge.py` (modificado)

`MockNav2Bridge` recibió `send_goal()` y `is_navigation_active()`, ambos
consistentes con el comportamiento mock existente (`navigation_delay_s`,
historial de llamadas vía nuevo campo `send_goal_calls`, `_task_active`
interno actualizado en `navigate_to_waypoints`/`send_goal`/`cancel_navigation`).
Verificado con `isinstance(MockNav2Bridge(), NavigationPort) == True`.

### 7.8 `tests/integration/test_tour_orchestrator.py` (modificado)

La fixture `orchestrator_bundle` se reescribió para usar
`hardware.mock_adapter.MockHardwareAPI()` (instanciada directamente, sin
patrón singleton) en lugar de `src.hardware.RobotHardwareAPI.get_instance()`
+ `MockHighLevelClient`, reflejando el wiring real de `main.py`. El test
`test_emergency_stop_triggers_damp` se actualizó para verificar
`(await hardware_api.get_state())["state"] == "damped"` en lugar de
inspeccionar un historial de comandos del SDK simulado (`mock_client.history`),
ya que `MockHardwareAPI` no tiene ese historial — expone `get_state()` en
su lugar. Cobertura conservada: dispatch del tour, transición a
NAVIGATING, llamada al bridge, emergency stop, pregunta de usuario, cero
hardware real, cero ROS. Los tests legacy de `src.hardware` (en otros
archivos) no se modificaron ni eliminaron.

### 7.9 `smoke_test_offline_waypoint_follower.py` (modificado, solo docstring)

El docstring del módulo se corrigió para describir el escenario UNREACHABLE
real (punto fuera de los límites del mapa, `ABORTED`, `missed_waypoints=[1]`,
`error_code=204`/`GOAL_OUTSIDE_MAP`), eliminando la descripción obsoleta de
"celda ocupada interior". Ninguna línea funcional del smoke test cambió;
no se repitieron las corridas ROS de la Fase 2G.

### 7.10 `verify_sandbox_isolation.py` (modificado)

Se agregó `check_architecture_reconciliation_contract()`, invocada desde
`verify()` en ambos modos (estático y `--runtime`). Escanea
`src/navigation/models.py`, `src/navigation/port.py`,
`src/core/tour_orchestrator.py` y `main.py` contra:

- presencia textual de `BasicNavigator`, `/cmd_vel_nav`, `CMD_VEL_FILTERED_TOPIC`;
- imports (vía AST, no substring) de `src.hardware` o cualquier submódulo.

No modifica ningún contrato existente del sandbox (Waypoint Follower, BT
Navigator, topics, hardware ya aceptados). No ejecuta modo live. Confirmado
en `PASS` en modo estático y `--runtime` (file scan), tanto en Windows como
en WSL Jazzy.

### 7.11 Tests nuevos

- `tests/unit/test_architecture_reconciliation_contract.py` (nuevo, 27
  tests): cubre 14.1 (import puro sin ROS, en subprocess aislado), 14.2
  (identidad de `NavWaypoint`/`NavigationStatus`/`NavigationPort` entre
  rutas de import), 14.3 (contrato de imports de `tour_orchestrator.py`),
  14.4 (runtime canónico en `main.py`/`settings.py`), 14.5 (cuarentena de
  símbolos legacy), 14.6 (dos capas de hardware, runtime canónico no
  importa la legacy), 14.7 (conformidad estructural de `_MinimalNavStub`,
  `MockNav2Bridge` e `AsyncNav2Bridge`, sin instanciar `AsyncNav2Bridge`
  de forma que cree hilos/recursos ROS más allá de su constructor sync),
  14.8 (sandbox launch/params sin cambios).
- `tests/unit/test_offline_navigation_sandbox_isolation.py` (extendido,
  +5 tests): `ArchitectureReconciliationStaticGuardTests` valida que el
  verificador estático incluye los 4 archivos de arquitectura, pasa
  limpio contra el estado actual, y detecta correctamente símbolos
  prohibidos e imports prohibidos inyectados en archivos temporales
  (sin tocar el repositorio real).

## 8. Defecto encontrado y corregido durante esta fase: contaminación de `sys.modules` entre archivos de test

Al ejecutar la suite completa (`pytest tests/unit/`), 24 sub-casos de un
test pre-existente (`test_invalid_inputs_exit_2_with_clean_json_and_no_traceback`,
en `test_offline_navigation_sandbox_isolation.py`) fallaron — pero solo
cuando se ejecutaban junto con el nuevo archivo de tests, nunca de forma
aislada. Causa raíz: `ModelCompatibilityTests.setUp()` en el archivo nuevo
instala mocks de `rclpy`/`geometry_msgs`/`nav2_simple_commander` en
`sys.modules` (vía `tests.mocks.mock_ros2.install_mocks`) para poder
importar `nav2_bridge.py` sin ROS real, pero no los removía al finalizar.
Esto dejaba un `rclpy` falso residente en `sys.modules` para el resto de
la sesión de pytest; un test posterior que hace `import rclpy` como
sondeo de disponibilidad (para decidir si `skipTest`) encontraba el mock y
asumía que ROS 2 estaba instalado, intentando entonces lanzar subprocesos
reales (`python3 smoke_test_*.py ...`) que fallaban por razones no
relacionadas. Corregido agregando `tearDown()` a `ModelCompatibilityTests`
que remueve los módulos mock instalados y restaura cualquier estado previo
de `sys.modules` para esos nombres. Verificado: la suite completa pasa de
forma estable en ejecuciones repetidas tanto combinando ambos archivos
como en la suite completa de `tests/unit/`.

Relacionado: los dos tests que verifican "importa sin ROS en runtime"
(`test_models_module_actually_imports_at_runtime`,
`test_port_module_actually_imports_at_runtime`) se reescribieron para
lanzar un subprocess limpio (`sys.executable -c "..."`) en lugar de
verificar `sys.modules` dentro del mismo proceso de test — la alternativa
original era frágil incluso después del fix de `tearDown`, porque
`ModelCompatibilityTests` importa legítimamente `nav2_bridge.py` (para
verificar identidad de clase), lo cual carga el `cv2` real de forma
permanente para el resto del proceso; eso no es un defecto de
`models.py`, es una consecuencia esperada de compartir un proceso de
test con otro test que sí necesita el bridge legacy completo.

## 9. Archivos creados

- `codigo ottoguide/src/navigation/models.py`
- `codigo ottoguide/src/navigation/port.py`
- `codigo ottoguide/tests/unit/test_architecture_reconciliation_contract.py`
- `documentacion general del proyecto/Arquitectura/ADR_002_RECONCILIACION_NAVEGACION_HARDWARE.md`
- `documentacion general del proyecto/Arquitectura/ARCHITECTURE_RECONCILIATION_2H0_REPORT.md`

## 10. Archivos modificados

- `codigo ottoguide/src/navigation/nav2_bridge.py`
- `codigo ottoguide/src/navigation/__init__.py`
- `codigo ottoguide/src/core/tour_orchestrator.py`
- `codigo ottoguide/main.py`
- `codigo ottoguide/tests/mocks/mock_nav2_bridge.py`
- `codigo ottoguide/tests/integration/test_tour_orchestrator.py`
- `codigo ottoguide/tools/hil/offline_navigation/smoke_test_offline_waypoint_follower.py` (solo docstring)
- `codigo ottoguide/tools/hil/offline_navigation/verify_sandbox_isolation.py`
- `codigo ottoguide/tests/unit/test_offline_navigation_sandbox_isolation.py`
- `documentacion general del proyecto/Arquitectura/ROS2_INTEGRATION.md`
- `documentacion general del proyecto/Arquitectura/ARQUITECTURA_OPERATIVA_RC1.md`
- `documentacion general del proyecto/Operaciones_HIL/Offline_Replay_SLAM/OFFLINE_NAVIGATION_SANDBOX_READINESS.md`

## 11. Archivos legacy preservados (no modificados)

- `codigo ottoguide/src/hardware/` (`__init__.py`, `interface.py`,
  `robot_hardware_api.py`) — `RobotHardwareAPI`, `RobotHardwareAPIError`,
  `SupportsUnitreeHighLevelControl`, `MAX_LINEAR_VELOCITY` sin cambios.
- `codigo ottoguide/hardware/real_adapter.py`, `sim_adapter.py`,
  `mock_adapter.py` — sin cambios.
- `codigo ottoguide/config/settings.py` — sin cambios (ya usaba
  exclusivamente `hardware.*` antes de esta fase).
- `codigo ottoguide/launch/offline_nav_sandbox.launch.py`,
  `codigo ottoguide/config/navigation/nav2_offline_sandbox_params.yaml` —
  sin cambios.
- Lógica ROS interna de `AsyncNav2Bridge` (`BasicNavigator`, `/cmd_vel`,
  `/cmd_vel_nav`, `/initialpose`, `ThreadPoolExecutor`,
  `MultiThreadedExecutor`) — sin cambios de comportamiento.

## 12. Tests

### 12.1 Compilación de fuentes (Windows, sin `__pycache__`)

```text
SOURCE_COMPILE_PASS
```

Para: `src/navigation/models.py`, `src/navigation/port.py`,
`src/navigation/__init__.py`, `src/navigation/nav2_bridge.py`,
`src/core/tour_orchestrator.py`, `main.py`,
`tests/unit/test_architecture_reconciliation_contract.py`,
`tests/integration/test_tour_orchestrator.py`.

Repetido bajo WSL Jazzy (con `rclpy` real disponible): mismo resultado,
incluyendo además `tests/mocks/mock_nav2_bridge.py`,
`tools/hil/offline_navigation/smoke_test_offline_waypoint_follower.py`,
`tools/hil/offline_navigation/verify_sandbox_isolation.py`,
`tests/unit/test_offline_navigation_sandbox_isolation.py`.

### 12.2 Tests dirigidos (Windows, `.venv`)

`tests/unit/test_architecture_reconciliation_contract.py`: **27/27 PASS**.

`tests/unit/test_offline_navigation_sandbox_isolation.py`: **240
passed, 48 skipped** (mismo conteo de skips que antes de esta fase;
los 5 tests nuevos de `ArchitectureReconciliationStaticGuardTests` no
introdujeron skips nuevos).

`tests/integration/test_tour_orchestrator.py`,
`tests/integration/test_api_server.py`: **ERROR en recolección**, igual
que antes de cualquier cambio de esta fase. Causa raíz: cadena de
dependencias ausentes en `.venv` de Windows (`pyttsx3` →, más
profundamente, `speech_recognition` y `aiohttp`), todas transitivas vía
`src.interaction`, ninguna relacionada con los cambios de esta fase. Ver
sección 13 (Limitaciones).

### 12.3 Tests dirigidos (WSL Jazzy, Python del sistema)

`tests/unit/test_architecture_reconciliation_contract.py`: **27/27 OK**
(incluye los dos tests de import-en-subprocess-limpio, que requieren
`sys.executable` real).

`tests/unit/test_offline_navigation_sandbox_isolation.py`: **264 OK**
(incluye los tests de CLI por subprocess real, que en Windows se
saltan por falta de `rclpy`, pero en WSL se ejecutan completos).

`tests/integration/test_tour_orchestrator.py`: no ejecutable bajo WSL
(falta `pytest_asyncio`, `statemachine`, y otras dependencias del
`.venv` de Windows en el Python de sistema de WSL; no existe un venv de
proyecto en WSL). Las verificaciones funcionales equivalentes se
realizaron por separado: import real contra `rclpy`/`nav2_simple_commander`
genuinos (sección 12.4) y AST sobre el archivo de test.

### 12.4 Verificación funcional adicional bajo WSL (real ROS 2 Jazzy)

```python
from src.navigation.nav2_bridge import AsyncNav2Bridge, NavWaypoint, NavigationStatus
from src.navigation.models import NavWaypoint as ModelNavWaypoint
from src.navigation.port import NavigationPort
# identity: True
b = AsyncNav2Bridge()
# isinstance NavigationPort: True
```

Confirmado contra el `nav2_simple_commander`/`rclpy` reales instalados
en WSL Ubuntu-24.04 (ROS 2 Jazzy), sin iniciar ningún nodo ni hilo de
spin (el constructor de `AsyncNav2Bridge` es síncrono y no toca ROS
hasta `await start()`, que no se invocó).

### 12.5 Verificadores estáticos

Modo estático (`verify_sandbox_isolation.py`, sin argumentos): **PASS**,
0 errores, en Windows y en WSL Jazzy.

Modo runtime de escaneo de archivos (`--runtime`, sin lanzar ROS):
**PASS**, 0 errores, en Windows y en WSL Jazzy. Confirmado que ningún
nodo ni proceso ROS se inició durante esta verificación (es exclusivamente
escaneo estático de archivos, incluso en modo `--runtime`).

### 12.6 Suite unitaria completa (Windows, `.venv`)

```text
326 passed, 48 skipped, 9 errors
```

Los 9 errores son exactamente los mismos preexistentes en
`tests/unit/test_content_interface.py` (`ModuleNotFoundError: pyttsx3`),
sin cambios. **0 errores nuevos.** Verificado estable en 3 ejecuciones
repetidas (mismo resultado en las tres).

### 12.7 Suite unitaria completa (WSL Jazzy, discovery)

```text
Ran 294 tests in 35.682s
FAILED (errors=3)
```

Los 3 errores son módulos ausentes en el Python de sistema de WSL
(`pydantic_settings`, `pydantic`, `httpx`, vía `test_settings.py` y
`test_factory_rest_client.py`), no relacionados con los archivos
modificados en esta fase, y consistentes con la ausencia de un venv de
proyecto dedicado en WSL (las fases anteriores también ejecutaron solo
los tests dirigidos en WSL, no discovery completo, por la misma razón).
294 tests corrieron exitosamente — mismo número que el baseline previo
a esta fase en Windows (294 passed antes de los cambios de 2H.0).

## 13. Limitaciones

- `tests/integration/test_tour_orchestrator.py` y
  `tests/integration/test_api_server.py` no pudieron ejecutarse
  end-to-end en ningún entorno disponible (Windows: faltan `pyttsx3`,
  `speech_recognition`, `aiohttp`; WSL: faltan `pytest_asyncio`,
  `statemachine`, `pydantic_settings`, y no existe venv de proyecto).
  Este es un gap pre-existente, anterior a esta fase, y no se intentó
  resolver instalando paquetes (fuera de alcance explícito). La
  corrección de la fixture (sección 7.8) se verificó mediante una
  reproducción funcional equivalente en un proceso aislado, con
  `pyttsx3`/`speech_recognition` stubbed solo en memoria de proceso
  (nunca instalados, nunca escritos a disco) para confirmar que la
  lógica de la fixture y de las dos aserciones modificadas son
  correctas contra el código real de `TourOrchestrator`/`MockHardwareAPI`.
- Esta fase no ejecuta runtime ROS, no valida hardware, y no cambia
  ningún comportamiento de navegación física. `PHYSICAL_NAVIGATION`
  permanece `NOT_READY`.
- `BasicNavigator.followWaypoints()` sigue sin integrarse ni validarse
  contra el sandbox; esta fase solo reconcilió contratos de tipos, no
  arquitecturas de runtime.

## 14. Readiness

```text
ARCHITECTURE_RECONCILIATION = READY_WITH_REPORT_CORRECTIONS_PENDING
CANONICAL_HARDWARE_CONTRACT = READY
CANONICAL_NAVIGATION_PORT = READY

LEGACY_HARDWARE_RUNTIME_IMPORTS_REMAINING = 0
LEGACY_HARDWARE_STACK_QUARANTINED = YES

LEGACY_NAVIGATION_RUNTIME_ACTIVE = YES
LEGACY_NAVIGATION_RUNTIME_IMPORTS_REMAINING = 1
LEGACY_NAVIGATION_QUARANTINED = NO
LEGACY_NAVIGATION_REPLACEMENT_PENDING = FASE_2H_1_AND_2H_2

WINDOWS_TARGETED_TESTS = PARTIAL_PREEXISTING_DEPENDENCY_BLOCK
WSL_TARGETED_TESTS = PARTIAL_PREEXISTING_DEPENDENCY_BLOCK
INTEGRATION_TEST_EXECUTION = NOT_COMPLETED
NEW_REGRESSIONS_DETECTED = 0

DIFF_CHECK_2H0 = PARTIAL_KNOWN_CRLF_LIMITATION
FASE_2H_0 = ACCEPTED_FUNCTIONALLY_WITH_REPORT_CORRECTIONS

GLOBAL_PLANNING_SANDBOX = READY
LOCAL_CONTROL_SANDBOX = READY
COLLISION_SAFETY_SANDBOX = READY
BEHAVIOR_SERVER_SANDBOX = READY
BT_NAVIGATOR_SANDBOX = READY
NAVIGATE_TO_POSE_SANDBOX = READY
WAYPOINT_FOLLOWER_SANDBOX = READY
FOLLOW_WAYPOINTS_SANDBOX = READY

ROS_RUNTIME_SANDBOX = PARTIAL
L2_ODOMETRY = NOT_READY
L3_LOCALIZATION_MAP = NOT_READY
PHYSICAL_NAVIGATION = NOT_READY
PHYSICAL_READINESS_CHANGED = NO
```

## 15. Próximo paso

Fase 2H.1 — Direct Nav2 Action Bridge Offline: implementar
`NavigationPort` mediante un cliente `rclpy.action.ActionClient` directo
contra `/offline_nav/navigate_to_pose` y `/offline_nav/follow_waypoints`,
sin `BasicNavigator` y sin publicar velocidad.
