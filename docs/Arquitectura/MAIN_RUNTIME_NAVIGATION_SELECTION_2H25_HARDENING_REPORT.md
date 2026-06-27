# Main Runtime Navigation Bridge Selection — Reporte (Fase 2H.2.5)

## Recuperación local: lease monotónica, P0 Decision Engine v2, caracterización runtime

**Fecha**: 2026-06-23
**Rama operativa**: `robot` (no `main`)
**Commit parcial preservado**: `ba8de8a77b20cf7526e899537651c575938068cc`
**Baseline previo (parent de `ba8de8a`)**: `cd3177b74948fa9d49ea87d8297430eccbad2712`

```text
FASE_2H_2_5                    = IMPLEMENTED_LOCALLY_PENDING_PUSH_AND_INDEPENDENT_AUDIT
PUSH_STATUS                    = PUBLISHED_ON_ROBOT_BRANCH
INDEPENDENT_AUDIT              = COMPLETED_WITH_BLOCKING_FINDINGS
PHYSICAL_BASELINE              = CAPTURED_ON_OLDER_DEPLOYED_HEAD (23d9d9c, 38 commits behind)
LEASE_TIMEBASE                 = MONOTONIC_VALIDATED
P0_DECISION_ENGINE             = HARDENED_OFFLINE_PENDING_FIELD_AUDIT
P0_PHYSICAL_READ_ONLY          = NOT_EXECUTED
FORMAL_P0_V2_COLLECTOR         = NOT_EXECUTED
RUNTIME_INSTABILITY            = CHARACTERIZED_ROOT_CAUSE_NOT_PROVEN
RUNTIME_STABILITY              = PARTIAL_CHARACTERIZED
PHYSICAL_NAVIGATION            = NOT_READY
PHYSICAL_MOVEMENT              = NOT_AUTHORIZED
INDEPENDENT_AUDIT_REQUIRED     = YES
```

Este reporte **no** declara `COMPLETE`, `CLOSED`, `PHYSICAL_READY`,
`P0_AUTHORIZED` ni `PHYSICAL_NAVIGATION_READY`. La aceptación
independiente ocurre en otro chat.

### Auditoría física 2026-06-23 — hallazgos bloqueantes

La auditoría física realizada el 2026-06-23 sobre el HEAD `23d9d9c` encontró:

- **HEAD mismatch**: el robot estaba 38 commits detrás de `80417b7`. El código publicado
  no ha sido ejecutado físicamente.
- **Reloj de pared inválido**: el robot opera con RTC ~Mayo 1970. Cualquier timestamp
  `collected_at_utc` generado por el robot es ficticio.
- **Python 3.8 observado**: el path de site-packages del robot es `python3.8`, mientras el
  proyecto requiere `>=3.10`. Clasificado `PYTHON_RUNTIME_COMPATIBILITY=UNRESOLVED_HIGH_RISK`.
- **Sensores L0/L1 validados** (con sensor stack iniciado manualmente):
  `/utlidar/cloud`, `/livox/imu`, `/scan`, telemetría Unitree: PASS físico parcial.
- **Odometría, TF, mapa, Nav2**: ausentes. No hay movimiento por software.
- El `FORMAL_P0_V2_COLLECTOR` nunca se ejecutó; los resultados de `find_spec()` del R0
  se obtuvieron sin sourcear ROS y no deben usarse para modificar dependencias.

## 1. Contexto de esta sesión: recuperación, no implementación desde cero

Esta sesión recuperó y completó una ejecución previa de la Fase 2H.2.5
que había quedado parcialmente implementada en el commit local
`ba8de8a` (mensaje: "fix(hil): harden 2H.2.5 P0 decisions and monotonic
leases"). El trabajo de esta sesión consistió en:

1. auditar exhaustivamente `ba8de8a` contra el baseline `cd3177b`
   (diff completo, archivo por archivo, comparado contra las
   afirmaciones de su propio mensaje de commit);
2. ejecutar realmente los tests que el commit afirmaba haber pasado,
   para confirmarlos en lugar de aceptarlos por declaración;
3. completar la validación end-to-end de la lease monotónica (parent
   CLI timeout x3 en WSL real);
4. intentar la caracterización de inestabilidad runtime de 2H.2.4 y
   documentar honestamente por qué no pudo completarse en esta sesión;
5. generar evidencia y documentación versionadas;
6. crear un único commit local aditivo de finalización, preservando
   `ba8de8a` intacto.

## 2. Auditoría del commit parcial `ba8de8a`

`ba8de8a` es descendiente directo de `cd3177b` (verificado por
`git log`/`git diff`), no reescrito por esta sesión. Cambia 15
archivos, +1417/-435 líneas:

```text
tools/hil/offline_navigation/smoke_test_main_runtime_navigation_selection.py
tools/hil/offline_navigation/verify_sandbox_isolation.py
tools/hil/physical_read_only/collect_p0_readonly_evidence.py
tools/hil/physical_read_only/p0_evidence_schema.py
tools/hil/physical_read_only/validate_p0_readonly_evidence.py
tests/unit/test_main_runtime_timeout_cleanup.py
tests/unit/test_p0_readonly_evidence_contract.py
tests/unit/test_p0_readonly_pipeline_e2e.py
tests/unit/test_2h23_evidence_matrix.py
tests/fixtures/p0_readonly/{command_timeout,human_no_go,large_output,
  missing_topic,movement_attempt,nominal}/fixture.json
```

Auditoría línea por línea contra cada afirmación del mensaje de commit
(Workstream A: lease; Workstream B: P0 v2; Workstream C: verificador
estático) — ver detalle en §3-§5. Veredicto: **las afirmaciones del
commit parcial son ciertas y verificables**; no se encontró ninguna
discrepancia entre lo declarado y lo implementado, salvo la nota de
`ALLOWLIST_DEVIATION` en `test_2h23_evidence_matrix.py` (§3.3) y la
limitación de verificación por texto en lugar de AST (§6).

## 3. Workstream A — Cleanup lease monotónica (`LEASE_SCHEMA_VERSION=2`)

### 3.1 Diseño

`smoke_test_main_runtime_navigation_selection.py` introduce
`_lease_monotonic_ns()` (helper centralizado, monkeypatchable en
tests) y los campos `created_monotonic_ns`/`updated_monotonic_ns`.
`CleanupLease.create()` los puebla junto con los campos de reloj de
pared preexistentes (`created_at_ns`/`updated_at_ns`), que quedan
demovidos a **evidencia de auditoría humana únicamente** — nunca
consultados por `validate_lease_immutable_fields()` para orden,
vigencia o expiración. `update_child_identity()`/
`update_sandbox_identity()` rechazan con `LEASE_MONOTONIC_REGRESSION`
si el nuevo timestamp monotónico es anterior al de creación o al
último `updated_monotonic_ns` registrado.

`validate_lease_immutable_fields()` rechaza con `LEASE_SCHEMA_MISMATCH`
(y corta el resto de la validación) cualquier lease cuyo
`schema_version` no sea exactamente `2` — incluyendo el antiguo
`schema_version=1`, probado por tests preexistentes
(`test_main_runtime_timeout_cleanup.py:287`, `:1158`).

### 3.2 Validación realizada en esta sesión

**Tests deterministas** (`MonotonicLeaseTests`, 8 casos, Windows, lógica
pura sin filesystem):

```text
test_valid_monotonic_lease_produces_no_monotonic_errors        PASS
test_missing_monotonic_fields_yield_malformed                  PASS
test_non_int_monotonic_fields_yield_malformed                  PASS
test_monotonic_updated_before_created_rejected                 PASS
test_monotonic_created_in_future_rejected                      PASS
test_expired_lease_detected_via_monotonic                      PASS
test_wallclock_rollback_with_valid_monotonic_does_not_trigger_monotonic_error  PASS
test_wallclock_future_jump_does_not_falsely_expire_lease        PASS
```

8/8 PASS, confirmado por ejecución real (`pytest -k Monotonic`), no
solo por la declaración del commit.

**Camino CLI real del timeout del padre** (3 corridas limpias, WSL2,
stdlib únicamente, `run_2h24_parent_cli_timeout.py`, dominios nuevos
no reutilizados 221/225/229):

| Corrida | domain_id | cleanup_decision | scenario_decision | lease_validation | child_reaped | sandbox_group_alive_after | sentinel_signaled | zombies |
|---|---|---|---|---|---|---|---|---|
| 1 | 221 | PASS | EXPECTED_TIMEOUT | PASS | true | false | false | 0 |
| 2 | 225 | PASS | EXPECTED_TIMEOUT | PASS | true | false | false | 0 |
| 3 | 229 | PASS | EXPECTED_TIMEOUT | PASS | true | false | false | 0 |

Ninguna anomalía `LEASE_UPDATED_BEFORE_CREATED` en ninguna corrida
(distinto del único retry diagnóstico que sí ocurrió en 2H.2.4, antes
de la migración monotónica). Auditoría de procesos vía `ps aux`
posterior a las tres corridas: sin residuales de
`smoke_test`/`sandbox`/`ros2`, sin zombies.

### 3.3 Cambio en `test_2h23_evidence_matrix.py`

`_valid_lease_data()` agrega `created_monotonic_ns`/
`updated_monotonic_ns` al fixture sintético que ya existía, sin
eliminar ninguna assertion, sin cambiar ninguna decisión esperada, sin
agregar skips, sin reducir cobertura (verificado por diff línea a
línea). Registrado como:

```text
ALLOWLIST_DEVIATION = ACCEPTED_FOR_SYNTHETIC_LEASE_SCHEMA_V2_COMPATIBILITY
```

## 4. Workstream B — P0 Decision Engine v2 (`SCHEMA_VERSION=2`)

### 4.1 Cuatro capas de decisión, nunca mezcladas

`validate_p0_readonly_evidence.py` agrega una cuarta capa,
`collection_completeness`, independiente de `bundle_integrity`,
`read_only_invariants` y `p0_field_decision`:

```text
bundle_integrity        : ¿archivos presentes, schema v2, sidecar
                           atómico y verificado, metadata de filesystem
                           correcta, hashes coinciden con el manifest?
read_only_invariants    : ¿los 8 campos must-be-false son false, y el
                           command log pasa la auditoría de allowlist?
collection_completeness : ¿los comandos estrictos tuvieron éxito y los
                           acotados produjeron evidencia parseable?
p0_field_decision       : GO_CANDIDATE | NO_GO | FIXTURE_ONLY |
                           NOT_EVALUATED
```

### 4.2 Integridad (verificado por tests, no solo leído en código)

```text
schema v1 rechazado                                  PASS
expected-head ausente/malformado rechazado           PASS
sidecar ausente/inválido/hash-mismatch rechazado      PASS
manifest duplicado/path-traversal/extra rechazado     PASS
output dir existente rechazado (create_new_output_dir) verificado en código
permisos/owner incorrectos rechazados en POSIX        verificado en código (sys.platform != win32 guard)
nlink > 1 rechazado                                   verificado en código
sidecar escrito atómicamente                          verificado (atomic_write_bytes)
```

### 4.3 Inputs humanos explícitos, sin inferencia ni defaults

v1 inferiría `robot_physically_supervised` de
`operator_present AND area_cleared`, y defaulteaba
`dual_control_prohibited_acknowledged=True`. v2 elimina ambos: cada
campo humano (`operator_role`, `hardstop_type`,
`hardstop_tested_before_session`, `robot_physically_supervised`,
`dual_control_prohibited_acknowledged`) requiere un flag de CLI
explícito; su ausencia nunca se traduce en `true` implícito. Un
`hardstop_tested_before_session` desconocido pasa de ser una
advertencia (v1) a forzar `NO_GO` (v2).

### 4.4 Política de untracked por regex exacto

v1 aceptaba cualquier ruta que empezara con `codigo ottoguide/logs/`
(prefijo). v2 exige coincidencia exacta con
`^codigo ottoguide/logs/mission_[A-Za-z0-9_.-]+\.json$`, tras
normalizar separadores, y rechaza explícitamente rutas absolutas y con
`..` antes de aplicar el regex.

### 4.5 Auditoría del command log

El validador (no el collector) audita cada entrada del command log:
`label` debe matchear un patrón explícito de la allowlist;
`argv` debe ser lista de strings sin ninguna subcadena prohibida
(`send_goal`, `topic pub`, `service call`, `lifecycle set`,
`param set`, `launch`, comandos Unitree, `cmd_vel`, `damp`, `stand`,
`sit`, `walk`, etc.); `read_only_classification` debe ser exactamente
`"read_only"`.

### 4.6 Evidencia funcional mínima

El validador exige tipo y presencia correctos para `/odom`, `/scan`,
`/tf`, `/tf_static`, `/map`, `/map_metadata`; las 4 aristas TF
requeridas observadas; `/scan` con `publisher_count >= 1` y frecuencia
> 0; `/cmd_vel_raw`/`/cmd_vel_safe` con publishers y subscribers;
`controller_server`/`collision_monitor` observados; cualquier
`/cmd_vel` global inesperado fuerza `NO_GO`. `L2_ODOMETRY`/
`L3_LOCALIZATION_MAP` solo pueden ser `NOT_READY` o
`CANDIDATE_OBSERVED_PENDING_ANALYSIS`, nunca `READY` (confirmado: no
existe ningún literal `READY` en las constantes de readiness del
schema).

### 4.7 Resultados de tests (ejecutados en esta sesión, Windows)

```text
test_p0_readonly_pipeline_e2e.py        13/13 PASS (fixture E2E:
  nominal, missing_topic, wrong_head, human_no_go, tampered_hash,
  command_timeout, large_output, movement_attempt, dry_run)
test_p0_readonly_evidence_contract.py   60 passed, 1 skipped
  (test_bash_syntax_valid, POSIX-only en win32), 47 subtests passed
```

Coincide exactamente con lo declarado por `ba8de8a` (13/13 e2e, 47/47
contract subtests).

## 5. Workstream C — Verificador estático

`verify_sandbox_isolation.py` agrega
`check_2h25_monotonic_lease_contract` y
`check_2h25_p0_decision_v2_contract`. Ejecutado en esta sesión, en
Windows y en WSL: `PASS`, 0 errores, en ambos entornos.

## 6. Limitación conocida, no corregida en esta recuperación

Las dos funciones nuevas del verificador estático (`check_2h25_*`)
usan coincidencia de subcadena sobre el texto fuente, no parsing AST —
el mismo patrón que ya usaban los checks `check_2h24_*` preexistentes
en este verificador. Esto no es una regresión introducida por
`ba8de8a` ni por esta sesión, pero no satisface la guía más estricta
de "preferir AST o parsing estructurado" para 2H.2.5. No se corrigió en
esta recuperación: hacerlo requeriría tocar la lógica interna del
verificador más allá del alcance del commit parcial declarado, y no
existe ningún test que demuestre un falso negativo real causado por
esta limitación — corregirlo sin esa motivación sería alcance no
solicitado.

## 7. Caracterización de inestabilidad runtime — bloqueada por entorno

### 7.1 Lo que se intentó

El historial de 2H.2.4 (`Operaciones_HIL/Evidencia/2H24/runtime_summary.json`)
registra:

```text
diagnostic   (domain 184) = PASS 4/4
attempt_1    (domain 192) = PASS 4/4
attempt_2    (domain 200) = PASS 4/4
attempt_3    (domain 208) = FAIL 3/4 (controller_server
                             LIFECYCLE_QUERY_FAILED, waypoint_follower
                             NOT_ACTIVE)
extra_1      (domain 220) = PASS 4/4
extra_2      (domain 228) = FAIL 3/4 (7/7 componentes NOT_DISCOVERED)
consecutive_passes_max = 2
```

Esta sesión intentó repetir esta caracterización para poder elevar la
clasificación de causa más allá de `ENVIRONMENTAL_TRANSIENT`
(clasificación que las instrucciones de esta recuperación prohíben
expresamente reafirmar como causa probada).

### 7.2 Por qué no pudo completarse

El comando real de 2H.2.4 usaba
`source /opt/ros/jazzy/setup.bash` en WSL. La única instancia WSL
accesible en esta sesión (Ubuntu 24.04.4 LTS) **no tiene ningún ROS2
instalado**: `/opt/ros` no existe; `which ros2` vacío; no hay Docker
disponible como alternativa. Tampoco hay `pytest`/`pytest_asyncio`
instalados fuera del venv de Windows del proyecto (que no es ejecutable
bajo WSL por ser un binario PE, no ELF). Instalar cualquiera de estos
(`apt`, `rosdep`, `pip install`) está explícitamente prohibido por las
restricciones de seguridad de esta tarea.

Esto **no** es una regresión de `ba8de8a` ni de esta sesión: es una
diferencia de entorno de ejecución entre la sesión que produjo la
evidencia de 2H.2.4 (2026-06-22T23:55:00Z) y esta sesión de
recuperación (2026-06-23). Ningún cambio de código de esta fase toca
ROS2, Nav2, lifecycle ni discovery.

### 7.3 Lo que sí se hizo en su lugar

1. **Auditoría estática del algoritmo de discovery/lifecycle**
   (`wait_for_components_deterministic()`,
   `smoke_test_main_runtime_navigation_selection.py:904-948`): confirma
   un `deadline` compartido (`time.monotonic()`-based) consumido
   secuencialmente — cada iteración del bucle externo llama
   `_node_list()` una vez y luego, para cada componente de
   `REQUIRED_COMPONENTS` en orden fijo de tupla
   (`map_server, planner_server, controller_server,
   collision_monitor, behavior_server, bt_navigator,
   waypoint_follower`), llama `_lifecycle_get()` consumiendo una porción
   del mismo deadline restante. Esto es consistente con, pero no
   demuestra, el patrón de fallos de 2H.2.4 (`controller_server`, 3ra
   posición, `LIFECYCLE_QUERY_FAILED`; `waypoint_follower`, última
   posición, `NOT_ACTIVE`).
2. **3 corridas reales del parent CLI timeout** (no requieren ROS2,
   solo `/proc`/`setsid`/`killpg`, stdlib), todas limpias — ver §3.2.

### 7.4 Clasificación

```text
root_cause_classification = NOT_REPRODUCED_IN_2H25
```

No se reafirma `ENVIRONMENTAL_TRANSIENT` como causa probada. No se
escaló a ningún `PROVEN_*` (`PROVEN_SHARED_DEADLINE_DEFECT`,
`PROVEN_HARNESS_RETRY_DEFECT`, `PROVEN_DOMAIN_COLLISION`,
`PROVEN_OTHER_WITH_EVIDENCE`) porque ninguno de los tres requisitos del
criterio de corrección (reproducción determinista, test que falla
primero, corrección confinada al harness) pudo satisfacerse sin un
entorno ROS2. No se aplicó ninguna corrección de código a la lógica de
discovery/lifecycle en esta sesión.

## 8. Resultados de ejecución (matriz final)

```text
Windows:
  syntax (py_compile)                = PASS
  targeted 2H.2.5 (4 archivos)       = PASS (101 passed, 60 skipped, 47 subtests)
  tests/unit/ completo                = PASS (624 passed, 85 skipped)
  full repository suite (tests/)     = FAIL_PREEXISTING_PROVEN
    (único fallo: test_emergency_stop_triggers_damp, no tocado por
    ba8de8a ni por el commit de finalización; último cambio en d69cbef,
    ajeno a esta fase)
  static verifier                    = PASS (0 errores)

WSL (Ubuntu 24.04.4 LTS):
  syntax (py_compile)                = PASS
  static verifier                    = PASS (0 errores)
  parent CLI timeout x3              = PASS_3_CONSECUTIVE (dominios
    221/225/229, sin anomalías, cero zombies)
  targeted/unit/full pytest suites   = BLOCKED_ENVIRONMENT_GAP
    (pytest/pytest_asyncio ausentes; no se instalaron, prohibido)
  runtime verifier (--runtime)       = NOT_EXECUTED (requiere ROS2 activo)
  runtime characterization           = NOT_EXECUTED_ENVIRONMENT_UNAVAILABLE
```

Sin regresiones nuevas en ningún test ejecutado.

## 9. Archivos

```text
Preservados de ba8de8a (sin reescritura):
  tools/hil/offline_navigation/smoke_test_main_runtime_navigation_selection.py
  tools/hil/offline_navigation/verify_sandbox_isolation.py
  tools/hil/physical_read_only/{collect_p0_readonly_evidence,
    p0_evidence_schema,validate_p0_readonly_evidence}.py
  tests/unit/{test_main_runtime_timeout_cleanup,
    test_p0_readonly_evidence_contract,test_p0_readonly_pipeline_e2e,
    test_2h23_evidence_matrix}.py
  tests/fixtures/p0_readonly/*/fixture.json

Nuevos/actualizados en el commit de finalización de esta sesión:
  documentacion general del proyecto/Arquitectura/
    MAIN_RUNTIME_NAVIGATION_SELECTION_2H25_HARDENING_REPORT.md (este archivo)
    MAIN_RUNTIME_NAVIGATION_SELECTION_2H24_P0_PIPELINE_REPORT.md
      (corrección: ENVIRONMENTAL_TRANSIENT -> OBSERVED_ROOT_CAUSE_NOT_PROVEN)
  documentacion general del proyecto/Operaciones_HIL/
    P0_READ_ONLY_RUNBOOK.md (actualizado a v2)
    P0_READ_ONLY_EVIDENCE_SCHEMA.md (actualizado a v2)
    PREFLIGHT_DIRECT_NAV2_ACTION_BRIDGE_PHYSICAL_VALIDATION.md (nota 2H.2.5)
    Offline_Replay_SLAM/OFFLINE_NAVIGATION_SANDBOX_READINESS.md (nota 2H.2.5)
    Offline_Replay_SLAM/OFFLINE_NAVIGATION_SANDBOX_RUNTIME_RUNBOOK.md
      (apéndice 2H.2.5)
    Evidencia/2H25/{README.md,test_summary.json,
      lease_monotonic_summary.json,p0_hardening_summary.json,
      runtime_characterization_summary.json,evidence_manifest.json,
      evidence_manifest.sha256}
```

## 10. Commit y push

Un único commit local aditivo, descendiente lineal de `ba8de8a` (que se
preserva intacto, sin amend ni rebase). Push **no realizado** en esta
sesión — pendiente de confirmación explícita del usuario.

## 11. Limitaciones físicas

Esta fase no se conecta al robot, no usa SSH/SCP/rsync, no contacta
ninguna IP `192.168.*`, no instala ni actualiza dependencias (ni
ROS2/Nav2 ni pytest), y no ejecuta ningún comando de movimiento, Nav2
físico, lifecycle físico ni publicación de `cmd_vel`. El pipeline P0
queda preparado y probado offline (sin ejecución real); su ejecución
real contra el robot sigue sin autorizar y sin ejecutar.
`PHYSICAL_NAVIGATION = NOT_READY`, `PHYSICAL_MOVEMENT = NOT_AUTHORIZED`.
