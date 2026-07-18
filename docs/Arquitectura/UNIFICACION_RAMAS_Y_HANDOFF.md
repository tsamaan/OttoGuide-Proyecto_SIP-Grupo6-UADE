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
- Remote autoritativo de desarrollo: `mirror`.
- Remote de publicacion controlada: `canonical`.
- Politica de `canonical`: `PUBLICATION_ONLY_FAST_FORWARD`; solo se permite actualizar `review/orchestrator-unification` despues del mirror, nunca ramas default.
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
RELATIONS_SNAPSHOT_AS_OF_HEAD = fc42fa5bd3d32c57766350b422745fced97dc69a
```

Los conteos son un snapshot asociado a `RELATIONS_SNAPSHOT_AS_OF_HEAD`; deben recalcularse antes de una nueva decision de integracion.

| branch | head | ahead | behind | domain | status | disposition | integrated_scope | residual_scope | next_review_stage |
|---|---|---:|---:|---|---|---|---|---|---|
| `review/orchestrator-unification` | `DYNAMIC_FROM_ACTIVE_REF` | 0 | 0 | Integracion canonica | Activa | `PRIMARY_AUTHORITY` | U0, U1, U2, U2R1, U2R2, U3P0, U3A, U3AR1, U3AR2, U3AR3, U3AR4, U3AR5, U3AR6, U3AR7, U3AR8, U3AR9, U3B, U3BR1, U3BR2 | U3C-U6 | U3C |
| `main` | `3a1f13574e4a27d9aff2bfd38b3659951e8cb264` | N/A | N/A | Snapshot publico huerfano | Sin ancestro comun | `DO_NOT_USE_AS_INTEGRATION_BASE` | Ninguno para continuidad | Solo referencia historica | Ninguno |
| `desarrollo` | `aafb7ad1565caced974b98bfdd6b5320901f49c8` | 181 | 0 | Base historica | Sin delta pendiente | `ANCESTOR_NO_PENDING_DELTA` | Arquitectura base heredada | Ninguno activo | Ninguno |
| `robot` | `f35ee544dac1afd64c04b949ed952fc6e6a9b6bc` | 40 | 9 | Robot/SITL/HIL | Parcialmente integrado | `U0_SELECTIVE_PORT_COMPLETE_RESIDUAL_DEFERRED` | Fundacion SITL, puertos y contratos relevantes | Validaciones fisicas reales diferidas | U5 |
| `feature/erirobot` | `a93226b450bd384686dc9f009e96677910af936e` | 135 | 4 | QR/vision | Integracion selectiva QR completa | `U2_SELECTIVE_QR_PORT_COMPLETE_REJECTED_FSM_AND_MOTION_REMAIN_UNPORTED` | QR observacional y registro estricto | FSM y motion rechazados/no portados | U5 |
| `InteraccionIA` | `bf2148d4ad6fc766694842573452b740e0886385` | 181 | 6 | Interaccion IA/audio | Fuente tecnica pendiente | `U3_SELECTIVE_TECHNICAL_SOURCE` | Ninguno aun en U3 | Worker supervisado, eventos, audio real | U3B |
| `pilar-web` | `80051eed9dfab20c982147b8a1d8bb6bebac0982` | 64 | 1 | Frontend/web | Frontend adaptado, backend descartado | `FRONTEND_ALREADY_ADAPTED_BACKEND_DROPPED` | Adaptacion frontend ya absorbida | Backend no canonico descartado | U4 si aplica |
| `teo` | `b67d16624f703885f604993fef0d2920227daeba` | 181 | 4 | Interaccion historica | Referencia historica | `HISTORICAL_INTERACTION_REFERENCE` | Ninguno directo | Ideas tecnicas ya superseded por U3 audit | U3B |
| `echezuria` | `28c1220325ac94a342d55788eb0f02e40dece941` | 226 | 10 | Fisico/historico | Referencia fisica historica | `HISTORICAL_PHYSICAL_REFERENCE` | Ninguno directo | Evidencia historica no valida HIL actual | U5 |

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
| `U3AR2` | `6d5594601603edba4b069261357a5838921da1b0` | `fix(interaction): close supervisor lifecycle gaps` (auditoria posterior: `REJECTED_PARTIAL_REMEDIATION`) |
| `U3AR3` | `ce0d69b2a8e4aa1026e71bb20a4dcd504e543074` | `fix(interaction): bound command ledger and own cleanup` (auditoria posterior: `REJECTED_PARTIAL_REMEDIATION`) |
| `U3AR4` | `3b1d9d4e39e5bbc5fea56b52d1d3a483b5ef8e78` | `fix(interaction): enforce terminal enqueue and task settlement` (auditoria posterior: `REJECTED_PARTIAL_REMEDIATION`) |
| `U3AR5` | `df66ccc83a1e3ded3892cbc34ad349d1e3c48396` | `fix(interaction): make close settlement retryable` (auditoria posterior: `REJECTED_PARTIAL_REMEDIATION`) |
| `U3AR6` | `657e1505eebc2b93f0e3408d248c59007c685f14` | `fix(interaction): serialize close and preserve primary termination reasons` (auditoria posterior: `REJECTED_PARTIAL_REMEDIATION`) |
| `U3AR7` | `9ab1e6305b4722b075790235c5f7902ba6a644f1` | `fix(interaction): preserve in-flight close failures` (auditoria posterior: `TARGET_DEFECT_ACCEPTED_RESIDUAL_RUNTIME_CONCURRENCY_GAPS_FOUND`) |
| `U3AR8` | `b697f1d358338f4910a802386ad10bfb35e4439d` | `fix(interaction): preserve terminal state and converge cleanup` |
| `U3AR9` | `e094f7a9cf11848ea43ca74ce23a596d9bb38797` | `fix(interaction): enforce terminal runtime postconditions` |
| `U3B` | `fc42fa5bd3d32c57766350b422745fced97dc69a` | `feat(orchestrator): wire supervised interaction lifecycle` (auditoria posterior: `REJECTED_PARTIAL_IMPLEMENTATION`) |
| `U3BR1` | `664e0a3f8776a8861182bed364ae5be2a8a74e18` | `fix(orchestrator): serialize emergency and interaction shutdown` |
| `U3BR2` | `728584290b9e19c8caf6a2c6f856c7f3eb20b7a3` | `fix(orchestrator): bound settlement and preserve emergency` (auditoria posterior: `REJECTED_PARTIAL_REMEDIATION`) |
| `U3BR3` | `DYNAMIC_HANDOFF_CHECKPOINT` | `fix(orchestrator): avoid self-settlement and bound runtime stop` |
| `U3AR10` | `PENDING_COMMIT` | `fix(interaction): settle async resources before loop teardown` |

El checkpoint vigente del handoff se obtiene dinamicamente con `HANDOFF_CHECKPOINT_COMMAND`; no se agrega al ledger el SHA del commit que todavia contiene una correccion en preparacion.

### Runtime de validacion U3BR3

```text
NOTEBOOK_RUNTIME = CPYTHON_3_13_2_WINDOWS
TARGET_RUNTIME = PENDING_SSH_DISCOVERY
DEPENDENCY_MODE = FULL_REQUIREMENTS_PROD_EXCEPT_UNITREE_EDITABLE
UNITREE_SDK_INSTALLATION = DEFERRED_TO_NATIVE_ROBOT_ENVIRONMENT
ENVIRONMENT_PARITY_CLAIM = NOT_MADE
PY313_U3A_COMPATIBILITY = SIX_PREEXISTING_FAILURES_NOT_MODIFIED_IN_U3BR3
PY313_U3A_REQUIRED_BEFORE_U3C = YES
```

Los seis fallos U3A observados en la notebook Python 3.13 son baseline preexistente de compatibilidad y no fueron modificados en U3BR3:

- `tests/integration/test_u3a_jsonl_worker_supervisor.py::test_duplicate_message_id_and_heartbeat_timeout`
- `tests/integration/test_u3a_jsonl_worker_supervisor.py::test_stderr_flood_event_queue_overflow_and_crash_after_ready`
- `tests/integration/test_u3a_jsonl_worker_supervisor.py::test_double_activation_pause_resume_stop_and_emergency_latch`
- `tests/integration/test_u3a_jsonl_worker_supervisor.py::test_close_while_pending_command_ledger_is_full`
- `tests/integration/test_u3a_jsonl_worker_supervisor.py::test_emergency_while_commands_are_pending_without_ack_clears_ledger`
- `tests/integration/test_u3a_jsonl_worker_supervisor.py::test_protocol_failure_during_terminate_preserves_primary_reason`

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

Una auditoria posterior (`U3AR2_AUDIT`) encontro que, igual que con `U3AR1`, varios de estos puntos seguian incompletos en la implementacion real a pesar de presentarse aqui como resueltos. `U3AR3` (seccion 12.4) cierra esas brechas residuales.

RESUELTO_EN_U3AR3 (no estaba realmente resuelto en `U3AR2` a pesar de lo documentado anteriormente en esta seccion):

- El ledger `_pending_commands` esta acotado por un limite explicito `max_pending_commands` (independiente de `command_queue_size`), aplicado atomicamente junto con la asignacion de secuencia y el enqueue bajo el mismo lock; un worker que drena `_command_queue` pero retiene sus ACKs falla cerrado con `ERR_PENDING_COMMAND_LIMIT` y categoria de terminacion `COMMAND_ACK_BACKPRESSURE`, sin que el limite anterior (`command_queue_size + 1` implicito) fuera realmente alcanzable en ese escenario.
- Un `COMMAND_ACCEPTED` con `interaction_id` incorrecto pero `message_id`/`command` correctos ahora falla con `ERR_CORRELATION`; antes el chequeo generico de `ERR_STALE_INTERACTION` se ejecutaba primero y preemptaba la correlacion especifica.
- La tarea de limpieza tras un fallo (`_self_clean_after_failure`) tiene ownership explicito (`self._cleanup_task`, nombrada, una sola instancia activa a la vez) en vez de ser un `asyncio.ensure_future(...)` sin referencia; `close()` y el camino de fallo de `start()` la esperan antes de continuar, y sus excepciones se recuperan y registran en vez de quedar sin retrieve.
- `close()` ya no sobreescribe una causa de terminacion primaria (`PROCESS_FAILED_EVENT`, `PROTOCOL_FAILURE`, `HEARTBEAT_TIMEOUT`, `COMMAND_ACK_BACKPRESSURE`, etc.) con `CLOSE_TERMINATE`/`CLOSE_KILL`; esas categorias mecanicas solo se aplican cuando el propio `close()` establece la terminacion desde un estado no fallido.
- El workaround de finalizacion de transporte de `asyncio.subprocess` esta centralizado en un unico helper, gateado explicitamente a CPython+Windows; en cualquier otra plataforma/runtime no se ejecuta ningun paso adicional ni `gc.collect()` global.
- El ledger de comandos pendientes se limpia deterministicamente al entrar en FAILED, EMERGENCY o CLOSED; al drenar `_command_queue` durante `emergency_stop()` tambien se eliminan del ledger los IDs de los envelopes descartados.
- `_enqueue_command` rechaza inmediatamente con `ERR_TERMINAL_STATE` cualquier intento de encolar un comando una vez que el supervisor ya esta en FAILED o CLOSED, evitando que un caller siga re-llenando `_command_queue` despues de que `_command_writer` ya fue cancelado por la limpieza de fallo.

PENDIENTE:

- Composicion del runtime supervisado en `main.py` y seleccion fail-closed de modo real (corresponde a U3C).
- Playback real (worker CXX17 aun no implementado).
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

`U3AR2` cerro once defectos que `U3AR1_AUDIT` encontro pendientes a pesar de la documentacion previa. Ver seccion 11 (`RESUELTO_EN_U3AR2`) para el detalle tecnico de cada cierre. En particular, `U3AR2` agrego:

- el codigo de error estable `ERR_CORRELATION` para fallos de correlacion de `COMMAND_ACCEPTED`;
- una estructura acotada de comandos pendientes (`_pending_commands`) en el supervisor, del tamano de `command_queue_size + 1` como maximo;
- un buffer de cola de stderr (`_stderr_partial_tail`) acotado a `stderr_tail_max_chars`, en vez de una variable local sin limite;
- cierre explicito y deterministico del transporte de `asyncio.subprocess` en `close()` y en el self-clean de fallo de arranque, en vez de depender del timing del recolector de basura;
- un proceso fake deterministico (usado solo en tests) para probar la escalada `terminate()` -> `kill()` sin depender de un proceso real cooperativo.

Gate obligatorio verificado en esa etapa: tres corridas independientes de
`pytest tests/integration/test_u3a_jsonl_worker_supervisor.py -W error::pytest.PytestUnraisableExceptionWarning`
con exit code 0 y cero warnings, mas una corrida adicional con `python -X dev` sin coincidencias de `unraisable`, `unclosed transport`, `event loop is closed`, `task was destroyed` o `never awaited`.

**Auditoria posterior (`U3AR2_AUDIT`): `REJECTED_PARTIAL_REMEDIATION`.** Igual que con `U3AR1`, una revision real de la implementacion de `U3AR2` encontro defectos residuales no detectados por sus propios tests: el ledger `_pending_commands` quedaba acotado solo de forma indirecta por `command_queue_size`, no por un limite explicito sobre el dict, y un worker que drenaba la cola de comandos pero retenia sus ACKs podia hacer crecer el ledger sin tope real; un mismatch de `interaction_id` en `COMMAND_ACCEPTED` disparaba `ERR_STALE_INTERACTION` (el chequeo generico) en vez de `ERR_CORRELATION`, porque ese chequeo corria antes de llegar a la rama de correlacion especifica; la tarea de limpieza de fallo seguia siendo un `asyncio.ensure_future(...)` sin referencia ni nombre, no contabilizada en las metricas de "tareas restantes"; `close()` podia sobreescribir una causa de terminacion primaria (p. ej. `PROCESS_FAILED_EVENT`) con la categoria mecanica `CLOSE_TERMINATE`/`CLOSE_KILL` si la escalada de cierre se disparaba sobre un supervisor ya fallido; y el workaround de finalizacion de transporte de Windows accedia a `_transport` desde un metodo no centralizado y ejecutaba `gc.collect()` de forma global e incondicional, sin gating de plataforma. Estos seis puntos quedaron registrados como `outstanding_defects_carried_to_u3ar3` en `unification-state.json` y se cerraron en `U3AR3` (seccion 12.4).

Restricciones vigentes (no modificadas por `U3AR2`):

- Solo existe worker loopback falso.
- No existe worker real CXX17 implementado.
- No existe audio real implementado.
- No existe validacion HIL.
- `U3A`/`U3AR1`/`U3AR2` no estan conectados a `TourOrchestrator`; esa integracion corresponde a `U3B`.

### 12.4 Estado U3AR3

`U3AR3` cierra los seis defectos que `U3AR2_AUDIT` encontro pendientes a pesar de la documentacion previa. Ver seccion 11 (`RESUELTO_EN_U3AR3`) para el detalle tecnico de cada cierre. En particular, `U3AR3` agrega:

- `max_pending_commands` como limite explicito y configurable del ledger de comandos pendientes, aplicado atomicamente bajo el mismo lock que la asignacion de secuencia y el enqueue; codigo de error `ERR_PENDING_COMMAND_LIMIT` y categoria de terminacion `COMMAND_ACK_BACKPRESSURE`;
- correlacion de `COMMAND_ACCEPTED` que se evalua antes del chequeo generico de interaccion obsoleta, de modo que un mismatch de `interaction_id` siempre produce `ERR_CORRELATION`, nunca `ERR_STALE_INTERACTION`;
- ownership explicito de la tarea de limpieza de fallo (`self._cleanup_task`, nombrada, unica instancia activa, esperada por `close()` y por el camino de fallo de `start()`, con sus excepciones recuperadas y registradas);
- preservacion de la causa de terminacion primaria en `close()` ante cualquier escalada mecanica posterior (`CLOSE_TERMINATE`/`CLOSE_KILL`);
- centralizacion y gating de plataforma (CPython+Windows) del workaround de finalizacion de transporte, sin `gc.collect()` global en otras plataformas;
- limpieza deterministica del ledger de comandos pendientes al entrar en FAILED, EMERGENCY o CLOSED, incluyendo los envelopes descartados durante `emergency_stop()`;
- rechazo inmediato (`ERR_TERMINAL_STATE`) de nuevos comandos una vez que el supervisor ya esta en un estado terminal.

Gate obligatorio verificado para esta etapa: tres corridas independientes de
`pytest tests/integration/test_u3a_jsonl_worker_supervisor.py -W error::pytest.PytestUnraisableExceptionWarning`
con exit code 0 y cero warnings, una corrida adicional con `python -X dev` sin coincidencias de `unraisable`, `unclosed transport`, `event loop is closed`, `task was destroyed`, `never awaited` ni `exception was never retrieved`, y una matriz de concurrencia (5 corridas con filtro sobre los tests de ledger/correlacion/cleanup/cierre inmediato/transporte).

Restricciones vigentes (no modificadas por `U3AR3`):

- Solo existe worker loopback falso.
- No existe worker real CXX17 implementado.
- No existe audio real implementado.
- No existe validacion HIL.
- `U3A`/`U3AR1`/`U3AR2`/`U3AR3` no estan conectados a `TourOrchestrator`; esa integracion corresponde a `U3B`.

**Auditoria posterior (`U3AR3_AUDIT`): `REJECTED_PARTIAL_REMEDIATION`.** Una revision focal posterior encontro cuatro defectos residuales en la implementacion real de `U3AR3`: `_enqueue_command()` no revalidaba FAILED/CLOSED/EMERGENCY/CLOSING despues de adquirir `_command_lock`; un rechazo por `ERR_QUEUE_FULL` consumia `_outgoing_sequence`; `_cancel_tasks()` podia agotar su deadline, registrar `_last_error` y retornar como si el settlement fuera completo; y `ERR_TERMINAL_STATE` se exponia como literal no canonico. Estos defectos quedaron registrados como `outstanding_defects_carried_to_u3ar4` en `unification-state.json`.

### 12.5 Estado U3AR4

`U3AR4` cierra la atomicidad terminal residual de enqueue y el settlement formal de tareas propias del supervisor JSONL. En particular:

- `_enqueue_command()` revalida `CLOSED`, `FAILED`, `EMERGENCY` y `CLOSING` dentro de `_command_lock`, inmediatamente antes de mutar cola, secuencia o ledger.
- La secuencia saliente solo avanza despues de un `queue.put_nowait()` exitoso; rechazos por cola llena, limite de pendientes, cierre, emergencia o terminalidad no consumen secuencia ni registran pending commands.
- `ERR_TERMINAL_STATE`, `ERR_QUEUE_FULL`, `ERR_CLOSING`, `ERR_EMERGENCY` y `ERR_TASK_SETTLEMENT_TIMEOUT` forman parte del contrato canonico en `runtime_port.py`.
- `_cancel_tasks()` devuelve un settlement explicito con nombres asentados, cancelados y pendientes; `start()` y `close()` no reportan exito limpio si quedan tareas propias vivas tras el deadline.
- La categoria estable `TASK_SETTLEMENT_TIMEOUT` solo se usa como razon primaria cuando no hay una causa primaria previa; fallos como `PROCESS_FAILED_EVENT`, `PROTOCOL_FAILURE`, `HEARTBEAT_TIMEOUT` o `STARTUP_TIMEOUT` se preservan y el settlement incompleto queda como error secundario.

Restricciones vigentes (no modificadas por `U3AR4`):

- Solo existe worker loopback falso.
- No existe worker real CXX17 implementado.
- No existe audio real implementado.
- No existe validacion HIL.
- `U3A`/`U3AR1`/`U3AR2`/`U3AR3`/`U3AR4` no estan conectados a `TourOrchestrator`; esa integracion corresponde a `U3B`.

**Auditoria posterior (`U3AR4_AUDIT`): `REJECTED_PARTIAL_REMEDIATION`.** Una revision focal posterior encontro dos defectos residuales en `close()`: un timeout de settlement durante cierre normal conservaba una terminacion mecanica (`GRACEFUL_CLOSE`, `CLOSE_TERMINATE` o `CLOSE_KILL`) en vez de promover `TASK_SETTLEMENT_TIMEOUT` como causa primaria; y el supervisor marcaba `CLOSED` antes de confirmar que todas las tareas propias se habian asentado, impidiendo un reintento publico de `close()` tras liberar una tarea no cooperativa.

### 12.6 Estado U3AR5

`U3AR5` cierra los defectos residuales de clasificacion y retry del settlement de cierre:

- Un timeout de settlement en cierre normal ahora registra `TASK_SETTLEMENT_TIMEOUT`, `unexpected=True` y `ERR_TASK_SETTLEMENT_TIMEOUT` como causa primaria, preservando el exit code.
- Las causas primarias reales previas (`PROCESS_FAILED_EVENT`, `PROTOCOL_FAILURE`, `HEARTBEAT_TIMEOUT`, `STARTUP_TIMEOUT`, `WRITE_FAILURE`, `EVENT_QUEUE_OVERFLOW`, `COMMAND_ACK_BACKPRESSURE` y `EMERGENCY_STOP`) se preservan ante un settlement incompleto posterior.
- `close()` solo marca `CLOSED` despues de que el child termino, el event stream fue senalizado, el transporte se finalizo y las tareas propias se asentaron.
- Si quedan tareas propias vivas, `close()` lanza `ERR_TASK_SETTLEMENT_TIMEOUT`, deja el runtime no cerrado y permite que una segunda llamada publica a `close()` complete el settlement tras liberar la tarea no cooperativa, sin respawn ni escaladas de proceso innecesarias.

Restricciones vigentes (no modificadas por `U3AR5`):

- Solo existe worker loopback falso.
- No existe worker real CXX17 implementado.
- No existe audio real implementado.
- No existe validacion HIL.
- `U3A`/`U3AR1`/`U3AR2`/`U3AR3`/`U3AR4`/`U3AR5` no estan conectados a `TourOrchestrator`; esa integracion corresponde a `U3B`.

**Auditoria posterior (`U3AR5_AUDIT`): `REJECTED_PARTIAL_REMEDIATION`.** Una revision focal posterior encontro que la auditoria de `U3AR6` rechazo `U3AR5` con tres defectos residuales: `EMERGENCY_STOP` podia ser sobreescrito por `CLOSE_TERMINATE`/`CLOSE_KILL`; `UNEXPECTED_EXIT` no estaba clasificado como causa primaria real; y los callers concurrentes de `close()` no estaban serializados.

### 12.7 Estado U3AR6

`U3AR6` cierra los tres defectos residuales de `U3AR5_AUDIT`:

- `EMERGENCY_STOP` se preserva como causa primaria ante cualquier escalada mecanica posterior de `close()`.
- `UNEXPECTED_EXIT` queda clasificado en `_REAL_PRIMARY_TERMINATION_REASONS` al igual que `PROCESS_FAILED_EVENT`, `PROTOCOL_FAILURE`, etc.
- Los callers concurrentes de `close()` usan un unico `_close_task` compartido mediante `asyncio.shield`, eliminando la posibilidad de que dos callers lancen escaladas paralelas sobre el mismo child.

Restricciones vigentes (no modificadas por `U3AR6`):

- Solo existe worker loopback falso.
- No existe worker real CXX17 implementado.
- No existe audio real implementado.
- No existe validacion HIL.
- `U3A`/`U3AR1`/`U3AR2`/`U3AR3`/`U3AR4`/`U3AR5`/`U3AR6` no estan conectados a `TourOrchestrator`; esa integracion corresponde a `U3B`.

**Auditoria posterior (`U3AR6_AUDIT`): `REJECTED_PARTIAL_REMEDIATION`.** La auditoria detecto que `close()` toma un snapshot `had_primary_failure_reason` antes de las esperas cooperativas. Si una causa primaria se registra DURANTE esas esperas (es decir, despues del snapshot pero antes del bloque `finally`), el `finally` observa `had_primary_failure_reason = False` y sobreescribe la causa primaria real con la mecanica `CLOSE_TERMINATE`/`CLOSE_KILL`. Adicionalmente: los gates de validacion obligatorios de `U3AR6` no fueron preservados; los tests rojos no probaron todas las claims; y hubo churn de line endings sobre el archivo completo de tests. El defecto `PRIMARY_TERMINATION_REASON_CAN_BE_OVERWRITTEN_WHEN_IT_APPEARS_DURING_CLOSE_ESCALATION` quedo registrado como pendiente para `U3AR7`.

### 12.8 Estado U3AR7

`U3AR7` cierra el defecto de snapshot obsoleto detectado en `U3AR6_AUDIT`:

- El bloque `finally` de `_close_impl()` reevalua en vivo `_is_real_primary_termination(self._termination)` en vez de reutilizar el snapshot `had_primary_failure_reason` tomado antes de las esperas cooperativas.
- El snapshot se conserva solo para decidir si se intenta el comando CLOSE cooperativo; la logica de clasificacion del `finally` opera sobre el estado actual del supervisor.
- Una causa primaria registrada durante la escalada (`terminate()`/`kill()`) se preserva ahora incluso cuando el supervisor estaba en estado no fallido cuando comenzo `close()`.

Gate de la fase roja verificado: cuatro tests rojos contra `EXPECTED_HEAD`, de los cuales dos son obligatorios — un test de ruta `terminate()` (`test_process_failed_event_during_terminate_preserves_primary_reason`) y un test de ruta `kill()` (`test_protocol_failure_during_kill_preserves_primary_reason`). Los cuatro fallan con `CLOSE_KILL`/`CLOSE_TERMINATE` en vez de la razon primaria correcta, y los cuatro pasan despues del fix.

**Auditoria posterior (`U3AR7_AUDIT`): `TARGET_DEFECT_ACCEPTED_RESIDUAL_RUNTIME_CONCURRENCY_GAPS_FOUND`.** El defecto objetivo fue aceptado. Se detectaron tres defectos residuales en concurrencia del runtime que no formaban parte del scope de `U3AR7`:

- `PUBLIC_TRANSITION_ROLLBACK_CAN_OVERWRITE_TERMINAL_STATE`: `activate()`, `pause()` y `resume()` restauran incondicionalmente el estado optimista ante cualquier excepcion, sobreescribiendo transiciones terminales concurrentes (FAILED, EMERGENCY) que hayan ocurrido durante el enqueue.
- `FAILURE_DURING_CLOSE_CAN_START_COMPETING_CLEANUP`: `_fail()` invocado mientras `_close_impl()` es el propietario del lifecycle crea un `_cleanup_task` competidor y llama `terminate()` de nuevo.
- `PROCESS_SIGNAL_CAN_RACE_WITH_ALREADY_EXITED_CHILD`: `_close_impl()` no absorbe `ProcessLookupError` cuando el child ya termino entre la comprobacion de `returncode` y la llamada a `terminate()`/`kill()`.

Estos tres defectos se cerraron en `U3AR8`.

### 12.9 Estado U3AR8

`U3AR8` cierra los tres defectos residuales de concurrencia detectados en `U3AR7_AUDIT`:

**Rollback condicional de transiciones publicas:**

- Se agrego el helper privado `_restore_optimistic_state_if_unchanged(optimistic, previous)`.
- `activate()`, `pause()` y `resume()` invocan este helper en el bloque `except`, que solo restaura el estado anterior cuando el estado actual sigue siendo exactamente el estado optimista impuesto por esa llamada Y ni `_closing` ni `_emergency_latched` estan activos Y el estado no es FAILED, EMERGENCY o CLOSED.
- Si un `_fail()` o `emergency_stop()` concurrente mueve el estado a FAILED o EMERGENCY durante el enqueue, el rollback no se ejecuta y el estado terminal prevalece.

**Single owner de cleanup durante close:**

- Se agrego el predicado privado `_close_owns_lifecycle()` que retorna `True` cuando `_closing` es `True`, `_close_task` existe y no ha terminado.
- En `_fail()`, cuando `_close_owns_lifecycle()` es `True`, la funcion registra la causa primaria, limpia el ledger, señaliza el event stream y retorna sin llamar a `process.terminate()` ni crear `_cleanup_task`.
- `_close_impl()` sigue siendo el unico dueno de las esperas, escaladas y cancelacion de tareas.

**Tolerancia a ProcessLookupError:**

- `_close_impl()` ahora absorbe `ProcessLookupError` en `terminate()` y en `kill()`, continuando normalmente con la espera del returncode.

Gate de la fase roja verificado: doce tests rojos contra `EXPECTED_HEAD` (6 rollback, 4 competing-cleanup, 2 process-lookup), todos fallan con el codigo actual y pasan despues del fix. `RED_TARGET_BEHAVIOR_REACHED_AND_FAILED_COUNT = 12 >= 6`.

Restricciones vigentes (no modificadas por `U3AR8`):

- Solo existe worker loopback falso.
- No existe worker real CXX17 implementado.
- No existe audio real implementado.
- No existe validacion HIL.
- `U3A` a `U3AR8` no estan conectados a `TourOrchestrator`; esa integracion corresponde a `U3B`.

### 12.10 Estado U3AR9

`U3AR9` cierra cuatro defectos de postcondiciones terminales identificados en la auditoria de `U3AR8`:

**DEFECT_1 — Identidad publica visible durante close:**

- La propiedad `active_interaction_id` retornaba el campo interno sin filtro, incluso cuando el supervisor estaba cerrando o en estado terminal.
- Fix: la propiedad ahora retorna `None` cuando `_closing` es `True` o el estado es `STOPPING`, `FAILED`, `EMERGENCY` o `CLOSED`.
- El campo interno `_active_interaction_id` se preserva para correlacion de wire; solo la vista publica se filtra.

**DEFECT_2 — ID interno retenido al llegar a CLOSED:**

- `_close_impl()` no limpiaba `_active_interaction_id` antes de asignar `_state = CLOSED`, en ninguna de las dos rutas (sin proceso, y ruta principal).
- Fix: `_active_interaction_id = None` se asigna inmediatamente antes de `_state = InteractionRuntimeState.CLOSED` en ambas rutas.

**DEFECT_3 — Evento tardio durante close restaura READY o ready=True:**

- Los handlers de `PLAYBACK_COMPLETED`, `INTERACTION_TIMEOUT`, `CANCELLED` y `FAILED`-con-interaction_id en `_process_event()` asignaban `_state = READY` y/o `_ready = True` sin verificar `_closing`.
- Fix: se agrego la guarda `and not self._closing` en cada handler. El ID interno puede limpiar y el evento puede publicarse; lo que no ocurre es la transicion a READY/ready.

**DEFECT_4 — EVENT_QUEUE_OVERFLOW llama terminate() directamente despues de _fail():**

- `_publish_event()` contenia un segundo bloque `if self._process is not None and self._process.returncode is None: self._process.terminate()` inmediatamente despues de `await self._fail(...)`.
- Esto duplicaba la senalizacion y omitia la verificacion de `_close_owns_lifecycle()` que `_fail()` realiza internamente.
- Fix: se elimino el bloque de terminate directo. `_fail()` es el unico dueno de la decision de terminar y de la creacion del cleanup task.

Adicionalmente, `_close_impl()` ahora establece `_state = STOPPING` al inicio, cuando el estado actual no es ya `FAILED`, `EMERGENCY` o `CLOSED`. Esto materializa el estado de cierre intermedio que el contrato publico exigia.

Gate de la fase roja verificado: ocho tests rojos contra `b697f1d` (4 identidad/STOPPING, 2 late-event, 2 overflow-owner), todos fallan con el codigo anterior y pasan despues del fix. `RED_TARGET_BEHAVIOR_REACHED_AND_FAILED_COUNT = 8 >= 5`.

Restricciones vigentes (no modificadas por `U3AR9`):

- Solo existe worker loopback falso.
- No existe worker real CXX17 implementado.
- No existe audio real implementado.
- No existe validacion HIL.
- `U3A` a `U3AR9` no estan conectados a `TourOrchestrator`; esa integracion corresponde a `U3B`.

### 12.11 Estado U3B

`U3B` conecta un `InteractionRuntimePort` inyectado al lifecycle de `TourOrchestrator` sin componer ni iniciar el runtime desde `main.py`.

- `TourOrchestrator.__init__` acepta `interaction_runtime: Optional[InteractionRuntimePort] = None` como parametro keyword-only.
- Cuando no hay runtime, el camino legacy de `ConversationManager` se conserva: scripted/libre, timeouts, auditoria y reanudacion existentes.
- Cuando hay runtime, el orquestador genera IDs `interaction:1`, `interaction:2`, construye `InteractionContext`, detiene navegacion antes de activar, consume eventos con un unico `next_event()` activo y no usa fallback a `ConversationManager`.
- La navegacion solo se reanuda despues de `PLAYBACK_COMPLETED` con el `interaction_id` esperado y despues de publicar `EventType.INTERACTION_COMPLETED` desde Python.
- Timeout, cancelacion, failure, cierre del worker, error del stream o `interaction_id` incorrecto fallan cerrado: sin completion, sin resume y con `runtime.stop()` best-effort acotado.
- EMERGENCY cancela el consumidor, dispara `runtime.emergency_stop()` como task separada y no espera al worker antes de `cancel_navigation`, velocidad cero y `Damp()`.
- `close()` cancela tasks de interaccion, intenta `runtime.stop()` si habia interaccion activa y no llama `runtime.start()` ni `runtime.close()`.

Evidencia focal preservada en la etapa U3B:

```text
tests/unit/test_u3b_orchestrator_interaction_runtime.py = 15 passed
tests/integration/test_u3b_orchestrator_loopback.py = 1 passed
tests/unit/test_orchestrator_lifecycle.py = 10 passed
tests/unit/test_shutdown_sequence.py = 7 passed
tests/unit/test_u1_integration_contracts.py = 37 passed
tests/integration/test_u1_status_contracts.py = 12 passed
tests/unit/test_u3a_wire_contracts.py = 25 passed
tests/integration/test_u3a_jsonl_worker_supervisor.py = 106 passed
```

Restricciones vigentes:

- La composicion global del runtime supervisado en `main.py` no esta implementada; corresponde a `U3C`.
- Solo existe worker loopback falso.
- No existe worker real CXX17 implementado.
- No existe audio real validado.
- No existe validacion HIL.

**Auditoria posterior (`U3B_AUDIT`): `REJECTED_PARTIAL_IMPLEMENTATION`.** La integracion base de U3B quedo aceptada solo parcialmente. La revision encontro que el ownership de tasks de interaccion no estaba serializado de forma suficiente ante emergencia/cierre: la ruta publica `emergency_stop()` podia competir con el lifecycle supervisado; el handle de emergencia podia ser sobrescrito y duplicar `runtime.emergency_stop()`; una cancelacion del consumidor podia invocar `runtime.stop()` despues de que EMERGENCY o CLOSING ya hubieran reclamado el outcome terminal; una completion tardia despues del latch de emergencia podia publicar completion o reanudar navegacion; y un timeout de settlement en `close()` podia limpiar el handle vivo y volver el cierre no reintentable.

### 12.12 Estado U3BR1

`U3BR1` cierra la auditoria parcial de `U3B` sin tocar composicion global, `main.py`, settings, API, runtime protocol ni supervisor:

- El camino supervisado de `on_enter_interacting()` crea una unica task lifecycle propia del runtime y ya no usa `_interaction_owner_task`.
- El resultado terminal de interaccion queda latcheado (`ACTIVE`, `COMPLETED`, `FAILED`, `EMERGENCY`, `CLOSING`) para serializar completion, fail, emergency y close.
- `emergency_stop()` publico y `on_enter_emergency()` reclaman `EMERGENCY`, cancelan la task de interaccion y aseguran una sola task de `runtime.emergency_stop()` sin bloquear velocidad cero ni `Damp()`.
- El consumidor cancelado no envia `runtime.stop()` si EMERGENCY o CLOSING ya tomaron ownership.
- `close()` reclama `CLOSING`, deduplica `runtime.stop()` por `interaction_id`, preserva handles vivos ante timeout de settlement y permite reintento.
- Las completions tardias despues de EMERGENCY/CLOSING no publican `INTERACTION_COMPLETED` ni reanudan navegacion.
- El camino legacy sin runtime sigue funcionando y ya no referencia el owner task eliminado.

Evidencia focal preservada en la etapa U3BR1:

```text
compileall = passed
tests/unit/test_u3b_orchestrator_interaction_runtime.py + tests/integration/test_u3b_orchestrator_loopback.py -W error::pytest.PytestUnraisableExceptionWarning = 3x 21 passed
tests/unit/test_u3b_orchestrator_interaction_runtime.py = 20 passed
tests/integration/test_u3b_orchestrator_loopback.py = 1 passed
tests/unit/test_orchestrator_lifecycle.py = 10 passed
tests/unit/test_shutdown_sequence.py = 7 passed
tests/unit/test_u1_integration_contracts.py + tests/integration/test_u1_status_contracts.py = 49 passed
tests/unit/test_u3a_wire_contracts.py + tests/integration/test_u3a_jsonl_worker_supervisor.py = 131 passed
focused regression matrix = 218 passed
```

Restricciones vigentes:

- La composicion global del runtime supervisado en `main.py` no esta implementada; corresponde a `U3C`.
- Solo existe worker loopback falso.
- No existe worker real CXX17 implementado.
- No existe audio real validado.
- No existe validacion HIL.

**Auditoria posterior (`U3BR1_AUDIT`): `REJECTED_PARTIAL_IMPLEMENTATION`.** La revision encontro cinco defectos residuales en el ownership de tasks y en el settlement acotado: `_cancel_interaction_task_safe` usaba `asyncio.wait_for` que no acota tareas stubborn que capturan `CancelledError` en su `except` y bloquean en `release_event.wait()`; el mismo patron fallido aparecia en `_cancel_interaction_emergency_task_safe` y en `on_enter_emergency`; el consumidor era una segunda `asyncio.create_task` anidada dentro de la task lifecycle, creando dos duenos del lifecycle; `emergency_stop()` cancelaba incondicionalmente `_interaction_task` sin verificar si era la task actualmente en ejecucion, causando auto-cancelacion cuando el consumidor llamaba a `emergency_stop()` desde dentro de la propia task; y las excepciones no cancellation dentro del consumidor no disparaban una transicion de emergencia observable. Estos cinco defectos se cerraron en `U3BR2`.

### 12.13 Estado U3BR2

`U3BR2` cierra los cinco defectos de settlement acotado y emergencia interna detectados en `U3BR1_AUDIT`:

**DEFECT_1 — Settlement no acotado en `_cancel_interaction_task_safe` y `_cancel_interaction_emergency_task_safe`:**

- `asyncio.wait_for(task, timeout=X)` no acota una task stubborn que ya entro en `except asyncio.CancelledError:` y esta bloqueada en `release_event.wait()`.
- Fix: se reemplaza por `asyncio.wait({task}, timeout=INTERACTION_TASK_SETTLE_S)` que siempre retorna `(done, pending)` despues del timeout. Si `task in pending`, se lanza `RuntimeError("interaction task settlement timeout")` sin limpiar el handle, permitiendo reintento. Solo si `task in done` se limpia `_interaction_task = None`.
- Se introduce la constante modular `INTERACTION_TASK_SETTLE_S: float = 0.5` patcheable en tests.

**DEFECT_2 — Settlement no acotado en `on_enter_emergency`:**

- `asyncio.wait_for(self._interaction_emergency_task, timeout=0.5)` en `on_enter_emergency` tenia el mismo problema. Fix: se reemplaza por `asyncio.wait({emerg_task}, timeout=INTERACTION_TASK_SETTLE_S)`. Los `RuntimeError` del settlement se absorben en `result.errors` para no propagar excepciones desde `on_enter_emergency` (que reverteria la transicion FSM de AsyncEngine).

**DEFECT_3 — Task lifecycle anidada (dos duenos de ciclo de vida):**

- `on_enter_interacting` creaba una task `_run_supervised_runtime_interaction`, que internamente creaba otra `asyncio.create_task(_consume_runtime_interaction_events)`, resultando en dos tasks con lifecycle separados.
- Fix: `_run_supervised_runtime_interaction` llama directamente `await self._consume_runtime_interaction_events(runtime, context)` sin crear una segunda task. El nombre de la task lifecycle cambia de `interaction-runtime-pending-{n+1}` a `interaction-runtime-interaction:{seq}` donde `seq` es el valor de `_interaction_sequence` al momento de crear la task.

**DEFECT_4 — Auto-cancelacion en `emergency_stop()` y `on_enter_emergency`:**

- Cuando el consumidor llama a `emergency_stop()` desde dentro de `_interaction_task` (p.ej. tras un fallo en `resume_tour()`), `emergency_stop()` cancela `self._interaction_task`, que es la task actualmente en ejecucion. Esto cancela el propio consumidor antes de que la FSM llegue a EMERGENCY.
- Fix: se agrega `current_task = asyncio.current_task()` y la cancelacion solo se ejecuta si `self._interaction_task is not current_task`. El mismo guard se aplica en `on_enter_emergency`.

**DEFECT_5 — Excepciones no cancellation en el consumidor no disparan emergencia:**

- Una excepcion no `CancelledError` en `_consume_runtime_interaction_events` propagaba hacia arriba sin transicion de estado observable.
- Fix: `_run_supervised_runtime_interaction` agrega `except asyncio.CancelledError: raise` seguido de `except Exception: emergency_stop()` en el camino del `await` directo. El bloque `finally` usa `current = asyncio.current_task()` para no cancelar la task actual.

Evidencia focal preservada en la etapa U3BR2:

```text
compileall = passed
tests/unit/test_u3b_orchestrator_interaction_runtime.py -W error::pytest.PytestUnraisableExceptionWarning = 3x 33 passed
tests/unit/test_u3b_orchestrator_interaction_runtime.py -X dev = 33 passed, 0 ResourceWarning/unraisable
concurrency matrix [asyncio_mode x workers] = 5x 33 passed
tests/unit/test_u3b_orchestrator_interaction_runtime.py = 33 passed
full suite = 2x 1196 passed, 7 failed (solo nodeids heredados conocidos), 109 skipped
```

Restricciones vigentes (no modificadas por `U3BR2`):

- La composicion global del runtime supervisado en `main.py` no esta implementada; corresponde a `U3C`.
- Solo existe worker loopback falso.
- No existe worker real CXX17 implementado.
- No existe audio real validado.
- No existe validacion HIL.

### 12.14 Estado U3AR10

`U3AR10` corrige el defecto confirmado `NO_PROCESS_CLOSE_PATH_BYPASSES_OWNED_TASK_SETTLEMENT` en
`JsonlInteractionWorkerSupervisor._close_impl()`, detectado en la auditoria forense de
`U3A_NATIVE_HOST_GATE_V3_20260630T215323Z` (ejecucion nativa Linux CPython 3.11.15 aarch64 en el
robot).

**Causa confirmada:** la rama `self._process is None` de `_close_impl()` realizaba una
finalizacion parcial propia (limpiaba `_active_interaction_id`, marcaba `CLOSED`, registraba
terminacion, limpiaba comandos pendientes, senalizaba el event stream) y retornaba antes de
llegar a la cola comun de finalizacion (`_cancel_tasks()`,
`_let_event_loop_close_subprocess_transports()`, verificacion de settlement-timeout). Cualquier
task creada por `start()` (`command-writer`, `stdout-reader`, `process-watcher`,
`heartbeat-monitor`) quedaba viva sin cancelar hasta que el event loop de pytest-asyncio la
destruia al finalizar el test, generando los mensajes `Task was destroyed but it is pending!`
atribuidos incorrectamente por pytest a `test_process_failed_event_leaves_no_owned_tasks` cuando
el `source_traceback` real apuntaba a la linea 3745 de
`test_close_no_process_clears_internal_interaction_id`.

**Fix minimo:** la rama sin proceso ahora converge en la misma cola de finalizacion que la rama
con proceso, en vez de duplicar un subconjunto parcial y retornar antes de tiempo.

**Clasificacion del defecto:** `PRODUCT` (no `FIXTURE` ni `MIXED`). Se auditaron todos los fakes
de proceso usados por los ocho nodeids originalmente atribuidos por pytest; ninguno requirio
cambios. El fallback privado de transporte de Windows/CPython no se extendio a POSIX: 30/30
ciclos secuenciales reales de start/close bajo `asyncio.run()` no mostraron fugas, confirmando
que la convergencia natural via `_cancel_tasks()` es suficiente.

Nuevos archivos de test (no modifican tests existentes):

- `tests/integration/test_u3a_async_resource_cleanup.py`
- `tests/support/u3a_async_cleanup_probe.py`

Evidencia focal:

```text
Linux CPython 3.11.15 (WSL Ubuntu-24.04, x86_64, uv-managed venv):
  13 tests nuevos, estricto (PYTHONDEVMODE=1, PYTHONASYNCIODEBUG=1,
    -W error::RuntimeWarning -W error::ResourceWarning) = 13 passed
  8 nodeids originalmente atribuidos, estricto = 8 passed
  N1-N5 x5 = 25/25 passed
  N6 x20 = 20/20 passed, PROTOCOL_FAILURE preservado en las 20 iteraciones
  probe outer-process x20 (no_process_close + real_close) = 40/40, cero patrones prohibidos
  full U3A run1 = 144 passed, 0 failed
  full U3A run2 = 144 passed, 0 failed
  TASK_DESTROYED_PENDING_COUNT: 4 -> 0
  RESOURCE_WARNING_COUNT: 1 -> 0

Windows CPython 3.13.2:
  U3B regression (test_u3b_orchestrator_interaction_runtime.py + test_u3b_orchestrator_loopback.py)
    = 45 passed
  full suite baseline (HEAD sin parche) = 9 failed, 1218 passed, 109 skipped
  full suite post-parche = 9 failed, 1218 passed, 109 skipped
  new_failure_nodeids = none (un miembro rotativo de la familia preexistente
    PY313_SUPERVISOR_CLOSE_READER_DRAIN_RACE por corrida, nunca una categoria nueva)
```

Restricciones vigentes (no modificadas por `U3AR10`): mismas que `U3BR2` (composicion global en
`main.py`, worker loopback falso, sin worker real CXX17, sin audio real validado, sin HIL).

## 13. Baseline de pruebas

Proveniencia: `U3BR2`, ejecucion focal posterior a cerrar settlement acotado y emergencia interna en `TourOrchestrator` con Python 3.10 local. Sustituye el baseline focal previo de `U3BR1`; la suite completa conserva los fallos heredados listados abajo si aparecen.

```text
Python = 3.10.11
pytest = 9.1.1
pytest-asyncio = 1.4.0
FastAPI = 0.138.0
httpx = 0.28.1
NumPy = 2.2.6
U3B_UNIT = 33 passed
U3B_LOOPBACK = 1 passed
ORCHESTRATOR_LIFECYCLE = 10 passed
SHUTDOWN_SEQUENCE = 7 passed
U1_CONTRACTS = 37 passed
U1_STATUS_CONTRACTS = 12 passed
U3A_WIRE_CONTRACTS = 25 passed
SUPERVISOR_TESTS = 106 passed
FOCUSED_REGRESSION_MATRIX = 218 passed
STRICT_UNRAISABLE_U3B = 3x 33 passed
FULL_SUITE = 1196 passed, 7 failed, 109 skipped
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
- `U3B_IMPLEMENTED`
- `UNIFICATION_COMPLETE`

## 21. Siguiente accion

```text
NEXT_ACTION = AUDIT_AND_PLAN_U3_INTERACTION_WORKER_OFFLINE_ADAPTATION_V1
```

NEXT_ACTION actualizado tras U3A:

```text
NEXT_ACTION = IMPLEMENT_U3B_ORCHESTRATOR_INTERACTION_LIFECYCLE_V1
```

NEXT_ACTION vigente tras U3AR7 (sin cambio):

```text
NEXT_ACTION = IMPLEMENT_U3B_ORCHESTRATOR_INTERACTION_LIFECYCLE_V1
```

NEXT_ACTION vigente tras U3AR8 (sin cambio):

```text
NEXT_ACTION = IMPLEMENT_U3B_ORCHESTRATOR_INTERACTION_LIFECYCLE_V1
```

NEXT_ACTION vigente tras U3AR9 (sin cambio):

```text
NEXT_ACTION = IMPLEMENT_U3B_ORCHESTRATOR_INTERACTION_LIFECYCLE_V1
```

NEXT_ACTION vigente tras U3B:

```text
NEXT_ACTION = IMPLEMENT_U3C_RUNTIME_COMPOSITION_AND_FAIL_CLOSED_MODE_SELECTION_V1
```

NEXT_ACTION vigente tras U3BR1 (sin cambio):

```text
NEXT_ACTION = IMPLEMENT_U3C_RUNTIME_COMPOSITION_AND_FAIL_CLOSED_MODE_SELECTION_V1
```

NEXT_ACTION actualizado tras U3AR10:

```text
NEXT_ACTION = PREPARE_U3C_RUNTIME_COMPOSITION_AND_FAIL_CLOSED_MODE_SELECTION_V2
```

No ejecutar U3C desde este handoff. La siguiente etapa debe componer el runtime supervisado en el lifespan sin introducir worker real CXX17, audio real ni HIL salvo autorizacion explicita.

## Anexo — Trabajo offline Nivel B (paralelo a la unificacion)

Registro de checkpoints offline de Nivel B que no forman parte de la secuencia U*, no acceden al robot y no alteran el `NEXT_ACTION` de unificacion:

- **MVP-ODOM-TF-R1** (offline, Nivel B): gate puro y fail-closed de readiness para `/odom` y `odom -> base_link` sobre la evidencia estacionaria MFR-R6. Resultado `NOT_READY` con blockers explicitos. Ver `docs/Arquitectura/ODOM_TF_R1_OFFLINE_READINESS_CONTRACT.md`. Estados: `/odom publication = NOT_STARTED`, `TF publication = NOT_STARTED`, `physical validation = PENDING`, `Nav2 physical = NOT_STARTED`. No hay publicacion ROS/TF, no hay captura dinamica, no hay acceso al robot. El `NEXT_ACTION` de unificacion permanece sin cambios.
