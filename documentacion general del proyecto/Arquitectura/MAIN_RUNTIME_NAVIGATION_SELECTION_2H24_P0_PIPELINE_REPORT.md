# Main Runtime Navigation Bridge Selection — Reporte (Fase 2H.2.4)

## Functionalize P0 read-only evidence pipeline and close cleanup TOCTOU race

**Fecha**: 2026-06-22
**Rama operativa**: `robot` (no `main`)
**Baseline preservado**: `476bb3fe9fca20031a055a49e72e871d1114c437`
**Parent del baseline**: `b879100fce1112abf516abbca15d5ecb7fd365af`
**Grandparent del baseline**: `82d494222b7d230539c39ce9626c3b79f98f2d3a`

```text
FASE_2H_2_4 = IMPLEMENTED_PENDING_INDEPENDENT_AUDIT
CLEANUP_RACE = FIXED_AND_TESTED
P0_PIPELINE_OFFLINE = FUNCTIONAL_PENDING_INDEPENDENT_AUDIT
P0_FIELD_COLLECTION_PACKAGE = PREPARED_NOT_AUTHORIZED
P0_PHYSICAL_READ_ONLY = NOT_EXECUTED
P1_P2_P3 = NOT_AUTHORIZED
PHYSICAL_NAVIGATION = NOT_READY
PHYSICAL_MOVEMENT = NOT_AUTHORIZED
FASE_2I = NOT_AUTHORIZED
RUNTIME_STABILITY = PARTIAL
INDEPENDENT_AUDIT_REQUIRED = YES
```

Este reporte **no** declara `COMPLETE`, `CLOSED`, `PHYSICAL_READY`,
`P0_AUTHORIZED` ni `PHYSICAL_NAVIGATION_READY`. La aceptación
independiente ocurre en otro chat.

## 1. Baseline y remotos

```text
local HEAD = origin/robot = mirror-lucas/robot = 476bb3f (verificado por
  git ls-remote antes de cualquier cambio)
lineage = 476bb3f -> b879100 -> 82d4942 (verificado por
  git merge-base --is-ancestor)
tracked worktree = clean al inicio
untracked = 225 archivos, todos bajo codigo ottoguide/logs/mission_*.json
  (preexistentes, allowlist)
```

## 2. Defectos que esta fase cierra

1. **Collector P0 no funcional**: `collect_p0_readonly_evidence.sh` (la
   versión 2H.2.3) creaba `OUTPUT_DIR` y, para cada comando, lo
   imprimía (`--dry-run`) o lo ejecutaba y descartaba su salida
   (`run_ro`) — nunca escribía ninguno de los 7 archivos JSON que su
   propio nombre de funciones (`session_meta`, `ros_graph`, ...)
   sugería.
2. **Validador incompleto**: exigía solo `p0_session_meta.json`,
   `p0_ros_graph.json` y `p0_hash_manifest.json`; no validaba TF/odom,
   sensores, cadena cmd_vel, checklist humano completo, gates de Git,
   ni ROS_DISTRO/RMW.
3. **Tests no integrados**: `test_p0_readonly_evidence_contract.py`
   construía un bundle sintético directamente en Python, sin pasar
   nunca por el collector real.
4. **Seguridad humana insuficiente**: el validador antiguo solo exigía
   que `operator_present`/`hardstop_present` existieran como claves,
   sin exigir que valieran `true` para una candidatura GO.
5. **Git insuficiente**: no se validaba HEAD esperado, limpieza del
   worktree tracked, ni allowlist de untracked.
6. **Carrera TOCTOU**: `_authorized_targets()` (dentro de
   `escalate_signal_to_group`, en
   `smoke_test_main_runtime_navigation_selection.py`) ejecutaba
   `identity_still_valid(member) and read_process_identity(pid).pgid == pgid`
   — dos lecturas de kernel independientes para el mismo PID, sin
   guarda ante que la segunda devolviera `None` (lo que produciría
   `AttributeError`), y sin protección genuina contra reutilización de
   PID entre ambas lecturas.
7. **Documentación contradictoria**:
   `PREFLIGHT_DIRECT_NAV2_ACTION_BRIDGE_PHYSICAL_VALIDATION.md` decía
   en su §D ("Matriz GO/NO-GO") que P0 "puede prepararse y ejecutarse
   ahora", contradiciendo el estado declarado
   `P0_PHYSICAL_READ_ONLY = PREPARED_NOT_AUTHORIZED` en el mismo
   documento.

## 3. Corrección de la carrera TOCTOU

`_revalidate_identity_for_group_signal(expected, target_pgid)`
(`smoke_test_main_runtime_navigation_selection.py`) reemplaza el patrón
de doble lectura: toma exactamente una lectura fresca de
`read_process_identity(expected.pid)` y autoriza solo si, contra esa
**misma** instantánea: no es `None`; `pid`/`start_ticks`/`uid` coinciden
con lo esperado; `pgid` coincide con lo esperado **y** con
`target_pgid`; `sid == target_pgid` (contrato de sesión del grupo); y
ningún identificador es protegido. `_authorized_targets()` usa este
helper tanto para el líder como, en su rama de respaldo, para cada
miembro previamente capturado — nunca se vuelve a llamar a
`list_pgid_members()` después del descubrimiento inicial (antes de
cualquier señal), de modo que un proceso que se uniera al PGID después
nunca puede ser autorizado.

Tests (`tests/unit/test_main_runtime_timeout_cleanup.py::TOCTOURaceFixTests`,
13 casos, 12 nuevos):

```text
test_old_double_read_pattern_would_raise_attributeerror   (reproduce el defecto)
test_single_read_no_toctou_double_read                    (prueba una sola lectura)
test_process_disappeared_returns_none_not_attributeerror
test_pid_reused_with_different_start_ticks_rejected
test_uid_mismatch_rejected
test_pgid_drifted_from_expected_rejected
test_pgid_matches_expected_but_not_target_rejected
test_sid_drifted_from_group_contract_rejected
test_protected_current_pgid_rejected
test_valid_candidate_returns_current_snapshot_ignoring_ppid_reparenting
test_member_discovery_happens_exactly_once_new_members_never_considered
test_leader_gone_known_member_revalidated_and_signalled   (E2E real, líder
                                                            termina, nieto vivo)
test_signal_delivery_process_lookup_error_recorded_not_raised
test_signal_delivery_permission_error_recorded_not_raised
test_escalation_never_raises_attributeerror_when_identity_flaps
test_unrelated_sentinel_never_authorized_for_foreign_pgid
```

Todos PASS en Windows (los de lógica pura) y en WSL (los POSIX, 16/16).

## 4. Camino CLI real del timeout del padre

2H.2.3 probó `_parent_timeout_cleanup` llamándola directamente
(`run_2h23_evidence_matrix.py`). 2H.2.4 agrega un modo de fault
injection oculto y gateado dentro del propio
`smoke_test_main_runtime_navigation_selection.py`
(`--fault-inject-hang-sandbox`, `argparse.SUPPRESS`, nunca visible en
`--help`; requiere `OTTOGUIDE_2H24_FAULT_INJECTION=1` o se niega de
inmediato con `FAULT_INJECTION_NOT_AUTHORIZED`), de modo que un driver
nuevo (`run_2h24_parent_cli_timeout.py`) puede invocar la **CLI real**
(`main()` -> `_parent_main()` -> `communicate(timeout=...)` -> `except
TimeoutExpired` -> `_parent_timeout_cleanup` -> JSON impreso -> exit
code) como un subproceso genuino, en vez de importar la función. El
modo nunca lanza ROS: el "sandbox" inyectado es un proceso inerte
aislado, exactamente como en 2H.2.3.

Resultado (`cleanup_decision` y `scenario_decision` como ejes
independientes, nunca mezclados — un timeout intencional nunca se
reporta como PASS funcional):

```text
cleanup_decision = PASS
scenario_decision = EXPECTED_TIMEOUT
parent_cli_exit_code = 1 (no-cero, capturado correctamente)
zombies_remaining = 0
sentinel: alive_after=true, signalled=false, reaped=true
```

Reproducido 3 veces (dominios 220/221-224 derivados, 221, y un retry
de un run anómalo — ver §7).

## 5. Pipeline P0 funcional

Arquitectura nueva, stdlib únicamente, argv-only (nunca `shell=True`,
`os.system`, `eval`):

```text
collect_p0_readonly_evidence.py   núcleo: modos dry-run/real/fixture,
                                   gather_*, build_bundle, write_bundle
p0_evidence_schema.py             constantes, nombres de archivo,
                                   I/O segura (dir 0700, archivos 0600,
                                   escritura atómica), helpers
                                   compartidos por collector y validador
collect_p0_readonly_evidence.sh   wrapper mínimo: resuelve su propio
                                   directorio, valida python3, exec
validate_p0_readonly_evidence.py  validador de tres capas
```

Tres modos mutuamente excluyentes (`MODE_CONFLICT` si se combinan
`--execute-read-only` y `--fixture-dir`); dry-run por defecto; real
triple-gateado (env + 5 flags de CLI + `--output-dir`); fixture gateado
por `OTTOGUIDE_P0_FIXTURE_MODE=YES`. Las siete invariantes read-only
(`movement_command_sent`, `goal_sent`, `cmd_vel_published`,
`damp_invoked`, `control_service_called`, `lifecycle_changed`,
`parameter_changed`) son constantes literales `False` en el código de
`build_bundle`, verificado por AST
(`test_movement_invariant_fields_are_literal_false_constants`) — ningún
fixture ni flag puede hacerlas `true`.

Validador de tres capas (`bundle_integrity`, `read_only_invariants`,
`p0_field_decision`), nunca mezcladas:

```text
0 = bundle real + integridad PASS + read-only PASS + GO_CANDIDATE
1 = integridad FAIL o read-only FAIL
2 = integridad + read-only PASS, pero NO_GO
3 = fixture válido, FIXTURE_ONLY
```

Un fixture con hallazgos NO_GO genuinos (p.ej. operador ausente) se
reporta `NO_GO`, no `FIXTURE_ONLY` — el estado de fixture solo capa el
techo (nunca permite `GO_CANDIDATE`), nunca oculta un hallazgo real.

Ver `P0_READ_ONLY_RUNBOOK.md` y `P0_READ_ONLY_EVIDENCE_SCHEMA.md` para
el detalle operativo y de esquema.

## 6. Tests

```text
test_p0_readonly_evidence_contract.py   28 tests, 42 subtests — contrato
                                         de fuente (wrapper + núcleo),
                                         autorización, validador
test_p0_readonly_pipeline_e2e.py        13 tests — collector real
                                         (fixture) -> bundle -> manifest
                                         -> validador, 8 casos requeridos:
                                         nominal, topic ausente, HEAD
                                         incorrecto, seguridad humana
                                         NO_GO, hash alterado, timeout de
                                         comando, salida excesiva
                                         (truncamiento), intento de
                                         declarar movimiento (ignorado)
test_main_runtime_timeout_cleanup.py    +16 tests (TOCTOURaceFixTests)
test_2h24_parent_cli_timeout.py         6 tests — guardas + E2E real
test_offline_navigation_sandbox_isolation.py
                                         +11 tests — guardas estáticos
                                         nuevos (TOCTOU + pipeline P0)
```

Fixtures nuevas (`tests/fixtures/p0_readonly/`): `nominal`,
`missing_topic`, `human_no_go`, `command_timeout`, `large_output`,
`movement_attempt`.

## 7. Resultados de ejecución

```text
syntax (py_compile + bash -n)        = PASS
targeted_windows                     = PASS (471 passed, 109 skipped)
windows_unit                         = PASS (596 passed, 109 skipped)
windows_full                         = FAIL_PREEXISTING_PROVEN (único
  fallo: test_emergency_stop_triggers_damp, idéntico al baseline)
targeted_wsl                         = PASS (531 passed, 25 skipped)
wsl_unit                             = PREEXISTING_ENVIRONMENT_GAP_PROVEN
  (634 passed, 38 skipped, 9 errores -- todos ModuleNotFoundError:
  pytest_asyncio, en test_content_interface.py, no tocado por esta fase)
wsl_full                             = BLOCKED_PREEXISTING_ENVIRONMENT_GAP
  (3 errores de colección en tests/integration/*, mismo
  ModuleNotFoundError: pytest_asyncio)
static_verifier (sin --runtime)      = PASS (0 errores)
runtime_verifier (--runtime, con
  ROS_LOCALHOST_ONLY=1 + ROS_DOMAIN_ID)= PASS (0 errores)
function_timeout_e2e (run_2h23_evidence_matrix.py x3, dominios 105/106/107)
                                      = PASS x3
parent_cli_timeout_e2e (run_2h24_parent_cli_timeout.py)
                                      = PASS x2 + 1 anomalía transitoria
  (LEASE_UPDATED_BEFORE_CREATED, consistente con drift de reloj de VM en
  WSL2 bajo ejecución rápida sucesiva; cleanup_evidence de esa corrida
  mostró igualmente 0 zombies/huérfanos; retry inmediato con dominio
  fresco = PASS) + 1 retry PASS = 3 corridas limpias contabilizadas
```

### 7.1 Estabilidad runtime — `PARTIAL`

```text
diagnostic   (domain 184) = PASS 4/4
attempt_1    (domain 192) = PASS 4/4
attempt_2    (domain 200) = PASS 4/4
attempt_3    (domain 208) = FAIL 3/4 (emergency_cancel: controller_server
                            LIFECYCLE_QUERY_FAILED, waypoint_follower
                            NOT_ACTIVE; cleanup_evidence limpio)
extra_1      (domain 220) = PASS 4/4
extra_2      (domain 228) = FAIL 3/4 (interaction_cancel: 7/7 componentes
                            NOT_DISCOVERED; cleanup_evidence limpio)
consecutive_passes_max = 2
RUNTIME_STABILITY = PARTIAL
failure_cause_classification = ENVIRONMENTAL_TRANSIENT
```

Ningún cambio de esta fase toca lifecycle, discovery o bring-up de
Nav2/ROS2 (los cambios de código se limitan a la revalidación de
identidad de procesos para señalización de cleanup, y a hooks de fault
injection que nunca se activan sin la variable de entorno explícita).
En ambos fallos, `cleanup_evidence` permaneció limpio (`group_alive_after
= false`, `owned_members_remaining = []`, sin zombies ni huérfanos en la
auditoría de `/proc` posterior), lo que indica que la falla fue de
discovery/lifecycle-query de ROS 2 bajo la virtualización de WSL2 tras
múltiples bring-ups consecutivos de Nav2 en la misma sesión, no una
regresión de este cambio. No se reintentó más allá de los 5 intentos
oficiales (192/200/208/220/228), consistente con la política de
resultado parcial.

### 7.2 Auditoría de procesos

Tras cada corrida de timeout E2E y cada corrida de estabilidad runtime
(vía `/proc`, nunca por nombre): sin residuales de
`smoke_test_main_runtime`/`run_2h23`/`run_2h24`/`offline_nav_sandbox`/
`ros2 launch`/`ros2-daemon`, sin zombies, en absolutamente todas las
corridas (incluidas las dos fallidas).

## 8. Archivos

```text
Nuevos:
  tools/hil/physical_read_only/collect_p0_readonly_evidence.py
  tools/hil/physical_read_only/p0_evidence_schema.py
  tools/hil/offline_navigation/run_2h24_parent_cli_timeout.py
  tests/unit/test_2h24_parent_cli_timeout.py
  tests/unit/test_p0_readonly_pipeline_e2e.py
  tests/fixtures/p0_readonly/{nominal,missing_topic,human_no_go,
    command_timeout,large_output,movement_attempt}/fixture.json
  documentacion general del proyecto/Operaciones_HIL/P0_READ_ONLY_RUNBOOK.md
  documentacion general del proyecto/Operaciones_HIL/P0_READ_ONLY_EVIDENCE_SCHEMA.md
  documentacion general del proyecto/Arquitectura/
    MAIN_RUNTIME_NAVIGATION_SELECTION_2H24_P0_PIPELINE_REPORT.md (este archivo)
  documentacion general del proyecto/Operaciones_HIL/Evidencia/2H24/*

Modificados:
  tools/hil/offline_navigation/smoke_test_main_runtime_navigation_selection.py
    (TOCTOU fix + fault injection hooks)
  tools/hil/offline_navigation/verify_sandbox_isolation.py
    (2 checks estáticos nuevos)
  tools/hil/physical_read_only/collect_p0_readonly_evidence.sh
    (reescrito como wrapper mínimo)
  tools/hil/physical_read_only/validate_p0_readonly_evidence.py
    (reescrito, tres capas)
  tests/unit/test_main_runtime_timeout_cleanup.py (+16 tests)
  tests/unit/test_offline_navigation_sandbox_isolation.py (+11 tests)
  tests/unit/test_p0_readonly_evidence_contract.py (reescrito)
  documentacion general del proyecto/Arquitectura/
    MAIN_RUNTIME_NAVIGATION_SELECTION_2H23_EVIDENCE_CORRECTION_REPORT.md
    (banner PARTIAL_SUPERSEDED_BY_2H24)
  documentacion general del proyecto/Arquitectura/
    ADR_002_RECONCILIACION_NAVEGACION_HARDWARE.md (addendum)
  documentacion general del proyecto/Operaciones_HIL/
    PREFLIGHT_DIRECT_NAV2_ACTION_BRIDGE_PHYSICAL_VALIDATION.md
    (elimina contradicción "P0 puede ejecutarse ahora")
  documentacion general del proyecto/Operaciones_HIL/
    PREFLIGHT_PROXIMA_SESION_FISICA_ODOM_TF.md (nota 2H.2.4)
  documentacion general del proyecto/Operaciones_HIL/HIL_TESTING_PROTOCOL.md
    (banner de no autorización)
  documentacion general del proyecto/Operaciones_HIL/Offline_Replay_SLAM/
    OFFLINE_NAVIGATION_SANDBOX_READINESS.md (actualización 2H.2.4)
  documentacion general del proyecto/Operaciones_HIL/Offline_Replay_SLAM/
    OFFLINE_NAVIGATION_SANDBOX_RUNTIME_RUNBOOK.md (apéndice 2H.2.4)
```

## 9. Commit y push

Un único commit aditivo, descendiente lineal de `476bb3f`, sin amend ni
rebase. Push secuencial: primero `origin robot`, verificación vía
`git ls-remote`, luego `mirror-lucas robot`, verificación final. Sin
`--force`. Detalle de hashes en
`Operaciones_HIL/Evidencia/2H24/README.md`.

## 10. Limitaciones físicas

Esta fase no se conecta al robot, no usa SSH/SCP/rsync, no contacta
ninguna IP `192.168.*`, no instala ni actualiza dependencias, y no
ejecuta ningún comando de movimiento, Nav2 físico, lifecycle físico ni
publicación de `cmd_vel`. El pipeline P0 queda preparado y probado
offline; su ejecución real contra el robot sigue sin autorizar y sin
ejecutar. `PHYSICAL_NAVIGATION = NOT_READY`,
`PHYSICAL_MOVEMENT = NOT_AUTHORIZED`, `FASE_2I = NOT_AUTHORIZED`.
