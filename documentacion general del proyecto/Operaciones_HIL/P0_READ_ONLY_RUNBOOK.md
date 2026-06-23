# P0 Physical Read-Only — Runbook (Fase 2H.2.4)

**Estado**: `P0_PHYSICAL_READ_ONLY = PREPARED_NOT_AUTHORIZED / NOT_EXECUTED`.

Este runbook describe el pipeline P0 (`tools/hil/physical_read_only/`):
un collector y un validador que, en una sesión física futura
**separadamente autorizada**, recolectarían evidencia de introspección
read-only del robot (Git, grafo ROS, TF/odometría, sensores, cadena
cmd_vel, checklist de seguridad humana) sin nunca moverlo. Ningún comando
de este pipeline envía un goal, publica velocidad, llama un servicio de
control, ni cambia un parámetro o estado de lifecycle, en ningún modo.

## 1. Precondiciones humanas (obligatorias para cualquier ejecución real)

- Operador físico presente junto al robot.
- Hardstop físico presente y, idealmente, probado antes de la sesión.
- Área despejada de personas y obstáculos relevantes.
- Reconocimiento explícito de que el movimiento **no** está autorizado
  por esta sesión.
- Sin control dual (nadie más opera el robot simultáneamente).

Ninguna de estas condiciones puede inferirse del código; el operador
las declara mediante flags de CLI en el momento de la ejecución real.

## 2. Autorización externa requerida

La ejecución real (`--execute-read-only`) exige **todo** lo siguiente
simultáneamente; si falta cualquiera, el collector se niega
(`P0_NOT_AUTHORIZED`) sin ejecutar ningún comando:

```text
--execute-read-only
OTTOGUIDE_P0_READ_ONLY_AUTHORIZED=YES   (variable de entorno)
--expected-head <sha-1 de 40 hex>
--operator-present yes
--hardstop-present yes
--area-cleared yes
--movement-not-authorized-acknowledged yes
--output-dir <directorio nuevo>
```

`--expected-head` ata la sesión a un commit publicado específico; el
collector registra `actual_head` (vía `git rev-parse HEAD`) y
`head_matches_expected`, pero la decisión final la toma el validador.

Adicionalmente, esta fase (2H.2.4) exige:

1. auditoría independiente de Fase 2H.2.4 completada;
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
  --output-dir /tmp/p0_fixture_bundle \
  --expected-head <sha-1 de 40 hex> \
  --operator-present yes --hardstop-present yes --area-cleared yes \
  --movement-not-authorized-acknowledged yes
```

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
  --output-dir <directorio_nuevo> \
  --expected-head <sha-1 de 40 hex> \
  --operator-present yes --hardstop-present yes --area-cleared yes \
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

Produce tres capas de decisión **independientes**:

```text
bundle_integrity      : PASS | FAIL
read_only_invariants  : PASS | FAIL
p0_field_decision     : GO_CANDIDATE | NO_GO | FIXTURE_ONLY | NOT_EVALUATED
```

`p0_field_decision` solo se evalúa si las dos primeras capas son
`PASS`. Un bundle de fixture con datos limpios llega a `FIXTURE_ONLY`
(nunca `GO_CANDIDATE`); un bundle de fixture con hallazgos reales (p.ej.
operador ausente) llega honestamente a `NO_GO`, no a `FIXTURE_ONLY` —
el estado de fixture nunca oculta un hallazgo real.

### Exit codes

```text
0 = bundle real válido + read-only válido + GO_CANDIDATE
1 = bundle_integrity FAIL o read_only_invariants FAIL
2 = integridad + read-only PASS, pero NO_GO
3 = fixture válido, FIXTURE_ONLY
```

## 8. GO / NO-GO

Para `GO_CANDIDATE` se exige simultáneamente:

```text
bundle_integrity = PASS
read_only_invariants = PASS
actual_branch == expected_branch == robot
actual_head == expected_head, head_matches_expected == true
tracked_worktree_clean == true
untracked_paths solo bajo codigo ottoguide/logs/, sin symlinks
operator_present == true
hardstop_present == true
area_cleared == true
robot_physically_supervised == true
movement_not_authorized_acknowledged == true
ros_distro == foxy
rmw_implementation == rmw_cyclonedds_cpp
/odom, /scan, /tf, /tf_static presentes en el grafo ROS
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
