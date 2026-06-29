# Unificacion de ramas y handoff operativo

## 1. Proposito

Este documento es el handoff canonico, autocontenido y actualizable para continuar la unificacion de OttoGuide desde otro equipo. Debe permitir retomar el trabajo sin depender de conversaciones de chat, carpetas locales historicas, copias separadas de ramas, adjuntos externos, reportes no versionados bajo `audit-reports/` ni conocimiento implicito del workspace original.

La rama autoritativa de continuidad es `review/orchestrator-unification`. Este documento y `unification-state.json` son el punto de entrada obligatorio para nuevas etapas de unificacion.

## 2. Fuente de verdad

Jerarquia de fuentes:

1. Codigo productivo del `TARGET_HEAD`.
2. Tests versionados del `TARGET_HEAD`.
3. Documentacion vigente del `TARGET_HEAD`.
4. Codigo estatico de ramas fuente.
5. Documentacion historica.

Reglas de lectura:

- El codigo productivo prevalece sobre comentarios antiguos.
- Los tests prueban solo lo que ejecutan.
- La evidencia historica HIL no equivale a HIL actual.
- Una rama fuente no se convierte en autoridad por tener codigo funcional.
- Chat y memoria externa no se citan como fuente del documento.
- No copiar credenciales ni material sensible historico.

## 3. Repositorio y remotos

- Repositorio mirror: `LucasCap12/OttoGuide-Proyecto_SIP-Grupo6-G1-EDU`.
- URL HTTPS del mirror: `https://github.com/LucasCap12/OttoGuide-Proyecto_SIP-Grupo6-G1-EDU.git`.
- El clon requiere autenticacion GitHub cuando el repositorio no sea accesible de forma anonima.
- Remote permitido para continuidad: `mirror`.
- Remote prohibido para esta linea de trabajo: `canonical`.
- Rama autoritativa: `review/orchestrator-unification`.
- `main` es un snapshot huerfano sin ancestro comun con la rama de integracion; no es base de continuidad ni de integracion.

No registrar credenciales, tokens ni secretos en este documento.

## 4. Baseline autoritativo y checkpoint dinamico

```text
ACTIVE_BRANCH = review/orchestrator-unification
ACTIVE_REF = mirror/review/orchestrator-unification
CURRENT_HEAD = DYNAMIC_FROM_ACTIVE_REF
CURRENT_HEAD_COMMAND = git rev-parse mirror/review/orchestrator-unification
HANDOFF_CHECKPOINT = DYNAMIC_FROM_FILE_HISTORY
HANDOFF_CHECKPOINT_COMMAND = git log -1 --format=%H -- docs/Arquitectura/unification-state.json
GENERATION_BASE_HEAD = bf1829d8a7313ec3820f093f460a8b20a823f90a
GENERATION_BASE_MESSAGE = docs(unification): add portable branch handoff
```

`GENERATION_BASE_HEAD` es el HEAD desde el cual se preparo esta correccion, no el SHA del commit que contiene la correccion. El HEAD actual y el checkpoint vigente se resuelven con Git; no se almacena dentro del archivo el SHA del commit que lo contiene.

## 5. Invariantes arquitectonicos

```text
ONE_FASTAPI = YES
ONE_TOUR_ORCHESTRATOR = YES
ONE_MISSION_FSM = YES
ONE_MOTION_AUTHORITY = YES
ONE_CAMERA_AUTHORITY_PER_DEVICE = YES
ONE_REAL_AUDIO_AUTHORITY = YES
WHOLESALE_BRANCH_MERGES = PROHIBITED
CLOUD_IN_REAL_MODE = PROHIBITED
SILENT_REAL_FALLBACK = PROHIBITED
WORKER_MOTION_AUTHORITY = PROHIBITED
PLAYBACK_COMPLETED_BEFORE_NAVIGATION_RESUME = REQUIRED
```

## 6. Genealogia

Linea historica principal:

```text
echezuria
-> desarrollo
-> robot
-> ramas locales historicas de integracion
-> review/orchestrator-unification
```

Linea historica de interaccion:

```text
teo
-> InteraccionIA
```

Fuentes selectivas laterales:

```text
feature/erirobot, pilar-web e InteraccionIA
-> fuentes selectivas laterales
```

La genealogia explica procedencia y contexto, pero no autoriza merges completos. Las integraciones deben ser selectivas y obedecer los invariantes arquitectonicos.

## 7. Matriz de ramas

`ahead` y `behind` se expresan como `HEAD...mirror/<branch>` desde `review/orchestrator-unification`: `ahead` = commits solo en la rama autoritativa; `behind` = commits solo en la rama comparada. Para `main`, no hay ancestro comun.

```text
RELATIONS_SNAPSHOT_AS_OF_HEAD = fa877e5693f66086731d849383072e0b16f22931
```

Los conteos son un snapshot asociado a `RELATIONS_SNAPSHOT_AS_OF_HEAD`; deben recalcularse antes de una nueva decision de integracion.

| branch | head | ahead | behind | domain | status | disposition | integrated_scope | residual_scope | next_review_stage |
|---|---|---:|---:|---|---|---|---|---|---|
| `review/orchestrator-unification` | `DYNAMIC_FROM_ACTIVE_REF` | 0 | 0 | Integracion canonica | Activa | `PRIMARY_AUTHORITY` | U0, U1, U2, U2R1, U2R2, U3P0, U3A, U3AR1, U3AR2 | U3B-U6 | U3B |
| `main` | `3a1f13574e4a27d9aff2bfd38b3659951e8cb264` | N/A | N/A | Snapshot publico huerfano | Sin ancestro comun | `DO_NOT_USE_AS_INTEGRATION_BASE` | Ninguno para continuidad | Solo referencia historica | Ninguno |
| `desarrollo` | `aafb7ad1565caced974b98bfdd6b5320901f49c8` | 172 | 0 | Base historica | Sin delta pendiente | `ANCESTOR_NO_PENDING_DELTA` | Arquitectura base heredada | Ninguno activo | Ninguno |
| `robot` | `f35ee544dac1afd64c04b949ed952fc6e6a9b6bc` | 31 | 9 | Robot/SITL/HIL | Parcialmente integrado | `U0_SELECTIVE_PORT_COMPLETE_RESIDUAL_DEFERRED` | Fundacion SITL, puertos y contratos relevantes | Validaciones fisicas reales diferidas | U5 |
| `feature/erirobot` | `a93226b450bd384686dc9f009e96677910af936e` | 126 | 4 | QR/vision | Integracion selectiva QR completa | `U2_SELECTIVE_QR_PORT_COMPLETE_REJECTED_FSM_AND_MOTION_REMAIN_UNPORTED` | QR observacional y registro estricto | FSM y motion rechazados/no portados | U5 |
| `InteraccionIA` | `bf2148d4ad6fc766694842573452b740e0886385` | 172 | 6 | Interaccion IA/audio | Fuente tecnica pendiente | `U3_SELECTIVE_TECHNICAL_SOURCE` | Ninguno aun en U3 | Worker supervisado, eventos, audio real | U3B |
| `pilar-web` | `80051eed9dfab20c982147b8a1d8bb6bebac0982` | 55 | 1 | Frontend/web | Frontend adaptado, backend descartado | `FRONTEND_ALREADY_ADAPTED_BACKEND_DROPPED` | Adaptacion frontend ya absorbida | Backend no canonico descartado | U4 si aplica |
| `teo` | `b67d16624f703885f604993fef0d2920227daeba` | 172 | 4 | Interaccion historica | Referencia historica | `HISTORICAL_INTERACTION_REFERENCE` | Ninguno directo | Ideas tecnicas ya superseded por U3 audit | U3B |
| `echezuria` | `28c1220325ac94a342d55788eb0f02e40dece941` | 217 | 10 | Fisico/historico | Referencia fisica historica | `HISTORICAL_PHYSICAL_REFERENCE` | Ninguno directo | Evidencia historica no valida HIL actual | U5 |

## 8. DAG de integracion

```text
U0
-> U1
-> U2
-> U3
-> U4
-> U5
-> U6
```

U2 y U3 son dominios separados: U2 trata QR/vision observacional; U3 trata runtime de interaccion, audio y worker supervisado. No mezclar correcciones entre dominios sin una etapa explicita.

## 9. Ledger de etapas

| etapa | commit | mensaje / estado |
|---|---|---|
| `ARCHITECTURE_BASELINE` | `d0211c8039e87a547a40c39c017e229fdcd51c77` | Baseline arquitectonico de reconciliacion |
| `U0` | `56936d804d448e983a4634c1456f5de2a41cc4f5` | `build(sitl): integrate WSL foundation` |
| `U1` | `7c45752b9b56f2b3fe22c92f84f6fbd52248186e` | `feat(runtime): add canonical integration contracts` |
| `U2` | `12cebbfd92ef80199b00f2e4ee8bbbd3f4d660ef` | `feat(vision): integrate QR station trigger` |
| `U2R1` | `b63acf66124df9bcc241cb63d4249c02673bae82` | `fix(vision): isolate QR from visual odometry` |
| `U2R2` | `99186ea545f50361556504d0418b68b117b88a2f` | `test(core): stabilize event module identity` |
| `U2R3` | N/A | `BLOCKED_NO_COMMIT_NOT_ATTRIBUTABLE_TO_U2R2` |
| `U2R4A_LITE` | N/A | `READ_ONLY_BASELINE_CONFIRMED_NO_COMMIT` |
| `U3P0` | `bf1829d8a7313ec3820f093f460a8b20a823f90a` | `docs(unification): add portable branch handoff` |
| `U3_AUDIT_V2` | N/A | `U3_INTERACTION_WORKER_OFFLINE_ADAPTATION_PLAN_READY` |
| `U3A` | `3ecc93f1a31ecc8e5e5de32414db0fcb0c37b2ae` | `feat(interaction): add strict loopback worker supervisor` |
| `U3AR1` | `fa877e5693f66086731d849383072e0b16f22931` | `fix(interaction): preserve supervisor terminal invariants` (auditoria posterior: `REJECTED_PARTIAL_REMEDIATION`) |
| `U3AR2` | `DYNAMIC_HANDOFF_CHECKPOINT` | `fix(interaction): close supervisor lifecycle gaps` |

El checkpoint vigente del handoff se obtiene dinamicamente con `HANDOFF_CHECKPOINT_COMMAND`; no se agrega al ledger el SHA del commit que todavia contiene una correccion en preparacion.

## 10. Estado QR

- QR es observacional: detecta estaciones, no gobierna movimiento.
- Registro de estaciones estricto: estaciones desconocidas no deben crear comportamiento implicito.
- Camara compartida: no introducir una segunda autoridad de camara por dispositivo.
- No segunda FSM: QR no crea una FSM paralela.
- No motion driver: QR no emite comandos de movimiento.
- Visual odometry queda deshabilitada en modo QR-only por falta de calibracion real.
- Deuda conocida: ArUco y tests parcialmente estructurales.
- Pendientes: validacion con camara real y confiabilidad QR en condiciones fisicas.

## 11. Estado de interaccion

RESUELTO_EN_U3A_U3AR1:

- `next_event` como API canonica de consumo (`async next_event(...)`).
- Wire coercion estricta (version 1) en `runtime_port.py`.
- Supervisor concreto `src/interaction/jsonl_worker_supervisor.py` con readiness, heartbeat, backpressure y cierre escalonado.
- Framing JSONL estricto (`ERR_FRAMING`); CRLF aceptado, frame sin LF rechazado.
- Lifecycle terminal del subprocess: EMERGENCY latcheado de forma persistente ante exit/heartbeat timeout/process watcher/transporte posterior; sin auto-respawn.
- Senal terminal independiente del event stream (`_event_stream_terminal`), desacoplada de insertar `None` en una cola que puede estar llena; consumidor bloqueado se desbloquea ante close/crash/protocolo invalido.
- Deduplicacion acotada de `message_id` (`max_seen_message_ids`) con fail-closed (`ERR_MESSAGE_LIMIT`).
- Registro unificado de terminacion (`_record_termination`) para cierre normal, emergencia, crash espontaneo, terminate/kill y fallos de protocolo.
- Drenaje de stderr por chunks sin deadlock ante lineas mayores que `max_line_bytes`.
- Tratamiento de evento `FAILED` diferenciado por proceso (`interaction_id=None`) vs interaccion (`interaction_id` presente, retorna a READY).
- Validacion de payload de correlacion obligatoria en `COMMAND_ACCEPTED` (`command`, `message_id`) y `FAILED` (`code`, `message`).
- Validacion de comandos por estado (`ACTIVATE`/`PAUSE`/`RESUME`/`STOP` exigen el estado previo correspondiente) con rollback si el enqueue falla.

Una auditoria posterior (`U3AR1_AUDIT`) encontro que varias de estas garantias estaban incompletas en la implementacion real de `U3AR1`, aunque la documentacion de esa etapa las presentaba como resueltas. `U3AR2` (seccion 12.3) cierra esas brechas; ver esa seccion para el detalle de que se corrigio realmente y con que evidencia.

RESUELTO_EN_U3AR2 (no estaba realmente resuelto en `U3AR1` a pesar de lo documentado entonces):

- El evento `FAILED` a nivel de proceso ahora termina el child y cierra el event stream de forma determinista tras publicarse, en vez de quedar publicado sin lifecycle terminal.
- `READY` solo se acepta durante `STARTING` con precondiciones estrictas; en cualquier otro estado (incluida `EMERGENCY`) se rechaza con `ERR_STATE` antes de mutar estado.
- El buffer parcial de stderr sin newline esta acotado a `stderr_tail_max_chars`, ya no crece sin limite ante un flood sin terminadores de linea.
- `COMMAND_ACCEPTED` correlaciona realmente contra los comandos pendientes enviados (`message_id`, `command`, `interaction_id`); `message_id` se valida como identificador wire estricto.
- Un `MappingProxyType` externo ya no se acepta como payload valido (`_freeze_payload` exige `dict` exacto).
- `WorkerTermination.reason` es siempre una categoria estable (`GRACEFUL_CLOSE`, `EMERGENCY_STOP`, `PROCESS_FAILED_EVENT`, `UNEXPECTED_EXIT`, `PROTOCOL_FAILURE`, `HEARTBEAT_TIMEOUT`, `STARTUP_TIMEOUT`, `WRITE_FAILURE`, `EVENT_QUEUE_OVERFLOW`, `CLOSE_TERMINATE`, `CLOSE_KILL`), nunca el mensaje humano.
- La escalada `terminate()` -> `kill()` en `close()` esta probada de forma deterministica contra un proceso fake, no solo inferida de un escenario real no concluyente en Windows.
- `asyncio.LimitOverrunError` se captura explicitamente y se reporta como `ERR_LINE_TOO_LARGE`.
- Un fallo de arranque (`start()`) limpia el child y las tareas propias sin requerir que el caller invoque `close()`.
- Las transiciones de `asyncio.subprocess` en Windows ya no producen `PytestUnraisableExceptionWarning`/`ResourceWarning` nuevos.

PENDIENTE:

- Wiring con `TourOrchestrator` (corresponde a U3B).
- Playback real (worker CXX17 aun no implementado).
- Fail-closed de composicion en el orquestador.
- Worker real CXX17.
- Benchmark.
- HIL.

## 12. Arquitectura U3 seleccionada

```text
SELECTED_ARCHITECTURE = PYTHON_CONTROL_PLANE_PLUS_DEDICATED_SUPERVISED_INTERACTION_WORKER
SELECTED_IPC = STDIN_STDOUT_JSONL_SUPERVISED_PROCESS
REAL_WORKER_LANGUAGE = CXX17
EVENT_CONSUMPTION_API = ASYNC_NEXT_EVENT
WIRE_PROTOCOL_VERSION = 1
```

La auditoria read-only `U3_AUDIT_V2` cerro la decision: el control plane Python supervisa un worker dedicado; el worker real futuro sera CXX17 salvo evidencia bloqueante posterior; la API de consumo de eventos es `async next_event(...)`; el transporte baseline es JSONL por stdin/stdout.

### 12.1 Estado U3A

`U3A` implementa infraestructura Python offline para el contrato de interaccion:

- validacion wire estricta version 1;
- `async next_event(...)` en `InteractionRuntimePort`;
- supervisor concreto `src/interaction/jsonl_worker_supervisor.py`;
- worker loopback falso `tests/support/u3a_loopback_worker.py`;
- readiness por `READY`, heartbeat local, backpressure, crash/protocol failure detection y cierre escalonado;
- tests offline deterministas.

Restricciones vigentes:

- Solo existe worker loopback falso.
- No existe worker real CXX17 implementado.
- No existe audio real implementado.
- No existe validacion HIL.
- U3A no esta conectada a `TourOrchestrator`; esa integracion corresponde a U3B.

### 12.2 Estado U3AR1

`U3AR1` fue una correccion focalizada sobre `U3A` que intento remediar invariantes terminales del supervisor JSONL antes de habilitar el wiring con `TourOrchestrator`. Una auditoria previa habia rechazado `U3A` con el resultado `U3A_REJECTED_PENDING_TERMINAL_INVARIANT_REMEDIATION`. `U3AR1` corrigio efectivamente:

- el latch de EMERGENCY, que persiste ante exit del worker, heartbeat timeout, process watcher y errores de transporte posteriores, sin transicionar a FAILED y sin respawn;
- el registro de toda terminacion (graceful, emergencia, crash espontaneo, terminate, kill) en una unica ruta interna;
- una senal terminal independiente del event stream que no depende exclusivamente de insertar `None` en una cola que puede estar llena;
- el framing JSONL estricto, exigiendo terminador LF y rechazando frames incompletos con `ERR_FRAMING`;
- la deduplicacion acotada de `message_id` con limite configurable y fallo cerrado al agotarse;
- el drenaje de stderr por chunks, evitando deadlock ante lineas mayores que `max_line_bytes`.

**Auditoria posterior (`U3AR1_AUDIT`): `REJECTED_PARTIAL_REMEDIATION`.** A pesar de que la version anterior de este documento declaraba resueltos otros diez puntos, una revision real de la implementacion encontro que NO lo estaban: el evento `FAILED` a nivel de proceso no terminaba el child ni cerraba el event stream; `READY` se aceptaba fuera de `STARTING`; el buffer parcial de stderr sin newline podia crecer sin limite; `COMMAND_ACCEPTED` no correlacionaba contra comandos pendientes reales ni validaba `message_id` como identificador estricto; un `MappingProxyType` externo se aceptaba como payload valido; `WorkerTermination.reason` almacenaba el mensaje humano en vez de una categoria estable; el fallback a `kill()` no estaba probado de forma deterministica; `asyncio.LimitOverrunError` no se capturaba explicitamente; un fallo de `start()` dejaba recursos sin limpiar sin un `close()` explicito del caller; y las transiciones de `asyncio.subprocess` en Windows producian `PytestUnraisableExceptionWarning` nuevos. Estos once puntos quedaron registrados como `outstanding_defects_carried_to_u3ar2` en `unification-state.json` y se cerraron en `U3AR2` (seccion 12.3).

Restricciones vigentes (no modificadas por `U3AR1`):

- Solo existe worker loopback falso.
- No existe worker real CXX17 implementado.
- No existe audio real implementado.
- No existe validacion HIL.
- `U3A`/`U3AR1` no estan conectados a `TourOrchestrator`; esa integracion corresponde a `U3B`.

### 12.3 Estado U3AR2

`U3AR2` cierra los once defectos que `U3AR1_AUDIT` encontro pendientes a pesar de la documentacion previa. Ver seccion 11 (`RESUELTO_EN_U3AR2`) para el detalle tecnico de cada cierre. En particular, `U3AR2` agrega:

- el codigo de error estable `ERR_CORRELATION` para fallos de correlacion de `COMMAND_ACCEPTED`;
- una estructura acotada de comandos pendientes (`_pending_commands`) en el supervisor, del tamano de `command_queue_size + 1` como maximo;
- un buffer de cola de stderr (`_stderr_partial_tail`) acotado a `stderr_tail_max_chars`, en vez de una variable local sin limite;
- cierre explicito y deterministico del transporte de `asyncio.subprocess` en `close()` y en el self-clean de fallo de arranque, en vez de depender del timing del recolector de basura;
- un proceso fake deterministico (usado solo en tests) para probar la escalada `terminate()` -> `kill()` sin depender de un proceso real cooperativo.

Gate obligatorio verificado para esta etapa: tres corridas independientes de
`pytest tests/integration/test_u3a_jsonl_worker_supervisor.py -W error::pytest.PytestUnraisableExceptionWarning`
con exit code 0 y cero warnings, mas una corrida adicional con `python -X dev` sin coincidencias de `unraisable`, `unclosed transport`, `event loop is closed`, `task was destroyed` o `never awaited`.

Restricciones vigentes (no modificadas por `U3AR2`):

- Solo existe worker loopback falso.
- No existe worker real CXX17 implementado.
- No existe audio real implementado.
- No existe validacion HIL.
- `U3A`/`U3AR1`/`U3AR2` no estan conectados a `TourOrchestrator`; esa integracion corresponde a `U3B`.

## 13. Baseline de pruebas

Proveniencia: `U3AR2`, ejecucion real posterior al cierre de los gaps de lifecycle, correlacion y recursos del supervisor JSONL (dos corridas completas de `tests/` con el `PINNED_PYTHON` de la etapa). Sustituye el baseline previo de `U3AR1`, que documentaba gaps como cerrados sin evidencia real.

```text
Python = 3.10.11
pytest = 9.0.2
pytest-asyncio = 1.3.0
FastAPI = 0.118.2
httpx = 0.28.1
NumPy = 2.2.6
WITNESS = 34 passed
FULL_SUITE = 1098 passed, 7 failed, 109 skipped, 67 subtests passed
KNOWN_TEST_DEBT = ORDER_DEPENDENT_SYS_MODULES_IDENTITY
FULL_SUITE_GREEN = NO
FULL_SUITE_RESULT = FAILED_WITH_ONLY_KNOWN_INHERITED_NODEIDS
```

`FULL_SUITE_RESULT = FAILED_WITH_ONLY_KNOWN_INHERITED_NODEIDS` indica que ambas corridas terminaron con exit code distinto de cero, y que los unicos nodeids en fallo son los siete heredados y conocidos abajo; ningun nodeid nuevo aparecio. No se afirma `FULL_SUITE_GREEN`.

Los siete fallos conocidos son:

- `tests/integration/test_web_ui_cors_and_origin.py::test_dashboard_redirects_to_web_ui_public_url_when_configured`
- `tests/unit/test_conversation_playback_lifecycle.py::test_t01_local_synthesize_no_type_error`
- `tests/unit/test_conversation_playback_lifecycle.py::test_t03_local_task_registered`
- `tests/unit/test_conversation_playback_lifecycle.py::test_t04_local_task_removed_after_completion`
- `tests/unit/test_conversation_playback_lifecycle.py::test_t06_alsa_exception_logged`
- `tests/unit/test_conversation_playback_lifecycle.py::test_t07_cancelled_task_no_error_log`
- `tests/unit/test_conversation_playback_lifecycle.py::test_t08_local_close_cancels_pending`

`codigo ottoguide/requirements_prod.txt` fija `numpy==2.3.3`. La ejecucion U2R4A-LITE uso NumPy 2.2.6; esa deriva no fue atribuida a los siete fallos.

## 14. Clon simple portable

Para trabajo normal basta un clon simple de la rama autoritativa:

```powershell
git clone --branch review/orchestrator-unification --no-single-branch https://github.com/LucasCap12/OttoGuide-Proyecto_SIP-Grupo6-G1-EDU.git OttoGuide-Unification
cd OttoGuide-Unification
git remote rename origin mirror
git fetch mirror --prune
git status --short --branch
git rev-parse HEAD
```

Esta modalidad es suficiente para desarrollo, auditorias focalizadas y documentacion. No requiere carpetas locales separadas para cada rama.

## 15. Inspeccion de ramas sin carpetas separadas

Ejemplos:

```powershell
git show mirror/InteraccionIA:<path>
git diff HEAD...mirror/feature/erirobot
git log --all --graph
```

No es obligatorio crear una carpeta por rama. Para revisar fuentes laterales, usar refs remotas de `mirror` y comandos `git show`, `git diff` y `git log`.

## 16. Workspace avanzado con worktrees

Estructura portable sugerida:

```text
<WORKSPACE_ROOT>/
  repo/
  worktrees/
    integration-phase6/
  audit-reports/
  envs/
```

Crear workspace avanzado desde cero:

```powershell
mkdir <WORKSPACE_ROOT>
cd <WORKSPACE_ROOT>
git clone --no-checkout https://github.com/LucasCap12/OttoGuide-Proyecto_SIP-Grupo6-G1-EDU.git repo
cd repo
git remote rename origin mirror
git fetch mirror --prune
git worktree add ..\worktrees\integration-phase6 -b review/orchestrator-unification mirror/review/orchestrator-unification
```

Variante si la rama local ya existe:

```powershell
cd <WORKSPACE_ROOT>\repo
git fetch mirror --prune
git worktree add ..\worktrees\integration-phase6 review/orchestrator-unification
```

No convertir rutas absolutas personales en contrato del repositorio.

## 17. Entorno Python

- Los venv no se copian entre equipos.
- Cada equipo debe recrear su entorno localmente.
- Cada etapa debe declarar version de Python, ruta usada y versiones criticas.
- Una ruta absoluta local del venv no forma parte del contrato del repositorio.
- No instalar dependencias como parte de una auditoria read-only.

## 18. Protocolo de reanudacion

Preflight minimo antes de continuar:

```powershell
git branch --show-current
git rev-parse HEAD
git log -1
git status
git diff
git fetch mirror
git rev-parse mirror/review/orchestrator-unification
```

Confirmar que la rama activa y `mirror/review/orchestrator-unification` coinciden con el estado esperado de la etapa.

## 19. Politica de actualizacion

Toda etapa con commit debe actualizar:

- `HEAD`.
- Ledger.
- Tests y baseline de pruebas.
- Deudas conocidas.
- Matriz de ramas si cambio.
- Claims prohibidos.
- `NEXT_ACTION`.

Despues del commit, el checkpoint dinamico debe coincidir con el HEAD remoto. No almacenar el HEAD actual dentro del propio archivo; el SHA del commit se obtiene mediante Git. Los commits anteriores si pueden incorporarse al ledger porque sus SHA ya son estables. Una auditoria read-only no modifica el documento por si misma ni crea checkpoint nuevo; la siguiente etapa con escritura incorpora su resultado al handoff y al JSON.

## 20. Claims prohibidos

No afirmar:

- `ROBOT_READY`
- `HIL_VALIDATED`
- `REAL_CAMERA_VALIDATED`
- `QR_RELIABILITY_VALIDATED`
- `VISUAL_ODOMETRY_VALIDATED`
- `REAL_AUDIO_VALIDATED`
- `PLAYSTREAM_VALIDATED_IN_CURRENT_HEAD`
- `PLAYSTOP_VALIDATED_IN_CURRENT_HEAD`
- `FULL_SUITE_GREEN`
- `U3_IMPLEMENTED`
- `UNIFICATION_COMPLETE`

## 21. Siguiente accion

```text
NEXT_ACTION = AUDIT_AND_PLAN_U3_INTERACTION_WORKER_OFFLINE_ADAPTATION_V1
```

NEXT_ACTION actualizado tras U3A:

```text
NEXT_ACTION = IMPLEMENT_U3B_ORCHESTRATOR_INTERACTION_LIFECYCLE_V1
```

No ejecutar U3B desde este handoff. La siguiente etapa debe conectar el lifecycle de interaccion al `TourOrchestrator` usando el contrato U3A, sin introducir audio real ni HIL salvo autorizacion explicita.
