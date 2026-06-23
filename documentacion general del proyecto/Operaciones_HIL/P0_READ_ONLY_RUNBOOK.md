# P0 Physical Read-Only — Runbook (Fase 2H.2.4, actualizado en 2H.2.5)

**Estado**: `P0_PHYSICAL_READ_ONLY = PREPARED_NOT_AUTHORIZED / NOT_EXECUTED`.

**Actualización 2H.2.5**: schema version 2 (`SCHEMA_VERSION = 2`,
`COLLECTOR_VERSION = "2H.2.5"`). Los gates humanos pasan de inferencia
conservadora a explícitos sin default (ver §1 y §2); la política de
untracked pasa de prefijo a regex exacto; el directorio de salida debe
ser nuevo (no preexistente); se agrega una cuarta capa de decisión
(`collection_completeness`). El validador ahora exige `--expected-head`
siempre (ya no es opcional).

Este runbook describe el pipeline P0 (`tools/hil/physical_read_only/`):
un collector y un validador que, en una sesión física futura
**separadamente autorizada**, recolectarían evidencia de introspección
read-only del robot (Git, grafo ROS, TF/odometría, sensores, cadena
cmd_vel, checklist de seguridad humana) sin nunca moverlo. Ningún comando
de este pipeline envía un goal, publica velocidad, llama un servicio de
control, ni cambia un parámetro o estado de lifecycle, en ningún modo.

## 1. Precondiciones humanas (obligatorias para cualquier ejecución real)

- Operador físico presente junto al robot, con rol/identidad declarada
  explícitamente (`--operator-role`, texto no vacío).
- Hardstop físico presente, con tipo declarado explícitamente
  (`--hardstop-type`, texto no vacío) y **probado antes de la sesión**
  (`--hardstop-tested-before-session yes`; en v2 un valor `unknown` o
  ausente ya no es una advertencia tolerada, es `NO_GO`).
- Área despejada de personas y obstáculos relevantes.
- Robot físicamente supervisado durante toda la colección
  (`--robot-physically-supervised yes`; en v2 esto ya **no** se infiere
  de `operator_present and area_cleared` — debe declararse explícitamente).
- Reconocimiento explícito de que el movimiento **no** está autorizado
  por esta sesión.
- Reconocimiento explícito de que el control dual está prohibido
  (`--dual-control-prohibited-acknowledged yes`; en v2 esto ya no tiene
  un valor por defecto `True` — debe declararse explícitamente).

Ninguna de estas condiciones puede inferirse del código ni asumirse por
defecto; el operador las declara una por una mediante flags de CLI en
el momento de la ejecución real.

## 2. Autorización externa requerida

La ejecución real (`--execute-read-only`) exige **todo** lo siguiente
simultáneamente; si falta cualquiera, el collector se niega
(`P0_NOT_AUTHORIZED`) sin ejecutar ningún comando:

```text
--execute-read-only
OTTOGUIDE_P0_READ_ONLY_AUTHORIZED=YES   (variable de entorno)
--expected-head <sha-1 de 40 hex>
--operator-present yes
--operator-role <texto no vacío>
--hardstop-present yes
--hardstop-type <texto no vacío>
--hardstop-tested-before-session yes
--area-cleared yes
--robot-physically-supervised yes
--dual-control-prohibited-acknowledged yes
--movement-not-authorized-acknowledged yes
--output-dir <directorio que NO debe existir aún>
```

`--expected-head` ata la sesión a un commit publicado específico
(comparación insensible a mayúsculas); el collector registra
`actual_head` (vía `git rev-parse HEAD`) y `head_matches_expected`, pero
la decisión final la toma el validador. `--output-dir` debe ser una
ruta que todavía no exista: `create_new_output_dir()` falla cerrado
(`OUTPUT_DIR_ALREADY_EXISTS`) si ya existe, es symlink, o no queda con
el propietario esperado — ya no se reutiliza un directorio preexistente
en modo real ni fixture de producción.

Adicionalmente, esta fase (2H.2.4/2H.2.5) exige:

1. auditoría independiente completada;
2. autorización explícita posterior a esa auditoría.

Ninguna de las dos existe todavía. **No ejecutar `--execute-read-only`
hasta que ambas existan.**

## 3. Dry-run (modo por defecto, seguro)

```bash
python3 tools/hil/physical_read_only/collect_p0_readonly_evidence.py --dry-run
# o, equivalentemente (es el default sin ningún flag de modo):
python3 tools/hil/physical_read_only/collect_p0_readonly_evidence.py
```

No ejecuta ningún comando externo. Imprime una descripción JSON: los
labels de comando que se ejecutarían, los 9 archivos que se generarían,
las guardas activas, y el aviso
`EXPECTED_HEAD_REQUIRED_FOR_FIELD_EXECUTION`. Nunca escribe un bundle.

## 4. Fixture mode (offline, para pruebas; nunca contra el robot)

```bash
export OTTOGUIDE_P0_FIXTURE_MODE=YES
python3 tools/hil/physical_read_only/collect_p0_readonly_evidence.py \
  --fixture-dir tests/fixtures/p0_readonly/nominal \
  --output-dir /tmp/p0_fixture_bundle_nuevo \
  --expected-head <sha-1 de 40 hex> \
  --operator-present yes --operator-role "tour operator" \
  --hardstop-present yes --hardstop-type "physical e-stop button" \
  --hardstop-tested-before-session yes --area-cleared yes \
  --robot-physically-supervised yes \
  --dual-control-prohibited-acknowledged yes \
  --movement-not-authorized-acknowledged yes
```

`--output-dir` debe ser una ruta nueva (no reutilizar un directorio de
una corrida anterior).

No ejecuta `git`/`ros2`/`printenv`/`hostname` ni ningún comando externo
real; consume un único archivo `fixture.json` con respuestas
prefabricadas y produce el mismo bundle de 7 archivos + manifest que la
ejecución real generaría, marcado `fixture_mode=true`. Sirve
exclusivamente para los tests de este repositorio
(`tests/unit/test_p0_readonly_pipeline_e2e.py`); nunca puede producir
`p0_field_decision=GO_CANDIDATE` (el validador lo capa en
`FIXTURE_ONLY` cuando los datos son limpios, o en `NO_GO` cuando no lo
son — nunca oculta un hallazgo real detrás del estado de fixture).

Fixture mode y `--execute-read-only` son mutuamente excluyentes
(`MODE_CONFLICT` si se pasan juntos).

## 5. Ejecución futura real (no realizada en esta fase)

```bash
export OTTOGUIDE_P0_READ_ONLY_AUTHORIZED=YES
python3 tools/hil/physical_read_only/collect_p0_readonly_evidence.py \
  --execute-read-only \
  --output-dir <directorio_nuevo_que_no_existe_aun> \
  --expected-head <sha-1 de 40 hex> \
  --operator-present yes --operator-role <rol/identidad real> \
  --hardstop-present yes --hardstop-type <tipo real> \
  --hardstop-tested-before-session yes --area-cleared yes \
  --robot-physically-supervised yes \
  --dual-control-prohibited-acknowledged yes \
  --movement-not-authorized-acknowledged yes
```

También puede invocarse vía el wrapper de shell equivalente
(`collect_p0_readonly_evidence.sh`, que solo resuelve su propio
directorio y hace `exec` al núcleo Python — nunca bifurca según los
flags). El wrapper existe para invocación directa en el host del robot
sin depender de cómo se resuelva `python3`/`python` en ese entorno.

## 6. Archivos generados (bundle completo)

```text
p0_session_meta.json
p0_ros_graph.json
p0_tf_and_localization.json
p0_sensors.json
p0_cmd_vel_chain.json
p0_safety_human_checklist.json
p0_command_log.json
p0_hash_manifest.json
p0_hash_manifest.sha256
```

Ver `P0_READ_ONLY_EVIDENCE_SCHEMA.md` para el detalle campo por campo.
Todos los archivos de datos son `0600`; el directorio es `0700`; nada es
symlink; cada escritura es atómica (temporal + fsync + `os.replace`).

## 7. Validador

```bash
python3 tools/hil/physical_read_only/validate_p0_readonly_evidence.py \
  <bundle_dir> --expected-head <sha-1 de 40 hex> --expected-branch robot
```

Produce cuatro capas de decisión **independientes** (v2 agrega
`collection_completeness`):

```text
bundle_integrity        : PASS | FAIL
read_only_invariants    : PASS | FAIL   (incluye auditoría del command log)
collection_completeness : PASS | FAIL   (comandos estrictos exitosos,
                                          comandos acotados con evidencia)
p0_field_decision       : GO_CANDIDATE | NO_GO | FIXTURE_ONLY | NOT_EVALUATED
```

Orden de evaluación: `bundle_integrity` FAIL o `read_only_invariants`
FAIL → `p0_field_decision = NOT_EVALUATED` (se saltan las capas
posteriores). `collection_completeness` FAIL → siempre `NO_GO`, nunca
`NOT_EVALUATED`. Un bundle de fixture con datos limpios llega a
`FIXTURE_ONLY` (nunca `GO_CANDIDATE`); un bundle de fixture con
hallazgos reales (p.ej. operador ausente) llega honestamente a `NO_GO`,
no a `FIXTURE_ONLY` — el estado de fixture nunca oculta un hallazgo
real.

`--expected-head` es ahora **obligatorio** en el validador (antes era
opcional); el validador rechaza con código 1 si no es un SHA-1 de 40
hex válido.

### Exit codes

```text
0 = bundle real válido, las cuatro capas PASS, GO_CANDIDATE
1 = bundle_integrity FAIL o read_only_invariants FAIL
2 = integridad + read-only PASS, pero completeness FAIL o NO_GO
3 = fixture válido, las cuatro capas PASS, FIXTURE_ONLY
```

## 8. GO / NO-GO

Para `GO_CANDIDATE` se exige simultáneamente:

```text
bundle_integrity = PASS
read_only_invariants = PASS
collection_completeness = PASS
actual_branch == expected_branch == robot
actual_head == expected_head (case-insensitive), head_matches_expected == true
tracked_worktree_clean == true
untracked_paths coinciden exactamente con
  ^codigo ottoguide/logs/mission_[A-Za-z0-9_.-]+\.json$ (regex completo,
  no solo prefijo), sin symlinks, sin path traversal
operator_present == true, operator_identity_or_role no vacío
hardstop_present == true, hardstop_type no vacío,
  hardstop_tested_before_session == true (literal, "unknown" => NO_GO)
area_cleared == true
robot_physically_supervised == true (declarado explícitamente, nunca inferido)
dual_control_prohibited_acknowledged == true (sin default)
movement_not_authorized_acknowledged == true
ros_distro == foxy
rmw_implementation == rmw_cyclonedds_cpp
collection_mode in {fixture, real_read_only}
/odom (nav_msgs/msg/Odometry), /scan (sensor_msgs/msg/LaserScan),
  /tf y /tf_static (tf2_msgs/msg/TFMessage) presentes con tipo correcto
/map (nav_msgs/msg/OccupancyGrid), /map_metadata (nav_msgs/msg/MapMetaData)
las 4 aristas TF requeridas observadas (map->odom, odom->base_link,
  base_link->utlidar_lidar, base_link->imu_link)
/scan con publisher_count >= 1 y frecuencia > 0
/cmd_vel_raw y /cmd_vel_safe presentes con publishers y subscribers
controller_server y collision_monitor observados
sin /cmd_vel global inesperado
fixture_mode == false
```

Cualquier ausencia produce `NO_GO` (o `FIXTURE_ONLY` si además
`fixture_mode == true` y no hay otros hallazgos). La ausencia de
sensores o de fuentes TF/odom **nunca** marca automáticamente
`L2_ODOMETRY`/`L3_LOCALIZATION_MAP` como `READY`; esos campos solo
pueden ser `NOT_READY` o `CANDIDATE_OBSERVED_PENDING_ANALYSIS`.

## 9. Rollback sin movimiento

Si la sesión se interrumpe en cualquier punto, no hay nada que revertir
en el robot: el collector nunca cambió ningún estado físico, lifecycle
ni parámetro. El único rollback posible es de evidencia: borrar el
`--output-dir` parcialmente escrito (los archivos se escriben de forma
atómica, por lo que nunca queda un JSON truncado) y, si se desea,
volver a intentar la colección con un nuevo `--output-dir`.

## 10. Qué NO autoriza este runbook

```text
P0 = PREPARED_NOT_AUTHORIZED
P1 = NOT_AUTHORIZED
P2 = NOT_AUTHORIZED
P3 = NOT_AUTHORIZED
PHYSICAL_NAVIGATION = NOT_READY
PHYSICAL_MOVEMENT = NOT_AUTHORIZED
```

Ningún comando de este runbook mueve al robot, activa Nav2 físico,
publica `cmd_vel`, ni cambia lifecycle/parámetros. Ver
`HIL_TESTING_PROTOCOL.md` para las restricciones de seguridad física
completas (ese documento se conserva como referencia; ningún paso suyo
está autorizado por esta fase).
