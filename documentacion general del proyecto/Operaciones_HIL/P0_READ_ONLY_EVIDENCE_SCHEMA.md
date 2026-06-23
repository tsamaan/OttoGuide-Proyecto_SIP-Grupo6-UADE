# P0 Physical Read-Only — Evidence Schema (Fase 2H.2.4, schema v2 en 2H.2.5)

Fuente de verdad en código: `tools/hil/physical_read_only/p0_evidence_schema.py`.
Este documento describe el contenido, no redefine el contrato; ante
cualquier discrepancia, el código manda.

**Actualización 2H.2.5**: `SCHEMA_VERSION = 2`, `COLLECTOR_VERSION =
"2H.2.5"`. El bundle ahora incluye también `p0_hash_manifest.sha256`
escrito atómicamente (antes se escribía con `Path.write_text` directo).
Todos los archivos comparten el mismo sobre (`schema.base_envelope`):

```json
{
  "schema_version": 2,
  "session_id": "<uuid4 hex, igual en los 7 archivos de una misma sesión>",
  "collected_at_utc": "<ISO8601 Z>",
  "collector_version": "2H.2.5"
}
```

## p0_session_meta.json

| Campo | Tipo | Obligatorio | Semántica |
|---|---|---|---|
| `actual_repo_root` | string | sí | Raíz del repo Git real (donde vive `.git`). |
| `actual_branch` | string | sí | Salida de `git branch --show-current`. |
| `expected_branch` | string | sí | Siempre `robot`. |
| `actual_head` | string | sí | Salida de `git rev-parse HEAD`. |
| `expected_head` | string\|null | sí | El `--expected-head` pasado al collector. |
| `head_matches_expected` | bool | sí | `expected_head` no vacío y `actual_head == expected_head`. |
| `tracked_worktree_clean` | bool | sí | Sin cambios tracked (`git status --short`). |
| `tracked_changes` | list[string] | sí | Líneas de `git status --short` que no son `??`. |
| `untracked_paths` | list[string] | sí | Rutas marcadas `??`. |
| `untracked_symlinks` | list[string] | sí | Subconjunto de `untracked_paths` que son symlinks (solo se computa en modo real; siempre `[]` en fixture). |
| `untracked_allowlist_only` | bool | sí | **v2**: cada ruta de `untracked_paths` coincide exactamente (no solo por prefijo) con `^codigo ottoguide/logs/mission_[A-Za-z0-9_.-]+\.json$`, tras normalizar separadores a `/`; rutas absolutas o con `..` se rechazan de inmediato. |
| `git_remote_metadata` | object | sí | `{"origin_url": "..."}`. **v2**: la URL se redacta (`schema.redact_git_url`) para no persistir credenciales embebidas tipo `https://user:token@host/...`. |
| `ros_distro` | string\|null | sí | `$ROS_DISTRO` (real) o del fixture. |
| `rmw_implementation` | string\|null | sí | `$RMW_IMPLEMENTATION`. |
| `cyclonedds_uri` | string\|null | no | `$CYCLONEDDS_URI`. |
| `hostname` | string\|null | sí | Real o del fixture. |
| `uid` | int\|null | sí | Real o del fixture. |
| `username` | string\|null | sí | Real o del fixture. |
| `collector_dry_run` | bool | sí | Siempre `false` en un bundle escrito (dry-run nunca escribe bundle). |
| `fixture_mode` | bool | sí | `true` si se usó `--fixture-dir`. |
| `collection_mode` | string | sí | **v2**: `"fixture"` o `"real_read_only"` — reemplaza la antigua inferencia implícita por un campo explícito de modo. |
| `field_collection_executed` | bool | sí | **v2**: `true` solo en modo real (reemplaza el campo ambiguo `physical_execution_performed`). |
| `operator_present` | bool | sí | Espejo del checklist humano. |
| `hardstop_present` | bool | sí | Espejo del checklist humano. |
| `movement_command_sent` | bool | sí | **Siempre `false`, constante literal en código.** |
| `goal_sent` | bool | sí | **Siempre `false`, constante literal.** |
| `cmd_vel_published` | bool | sí | **Siempre `false`, constante literal.** |
| `damp_invoked` | bool | sí | **Siempre `false`, constante literal.** |
| `control_service_called` | bool | sí | **Siempre `false`, constante literal.** |
| `lifecycle_changed` | bool | sí | **Siempre `false`, constante literal.** |
| `parameter_changed` | bool | sí | **Siempre `false`, constante literal.** |
| `physical_control_execution_performed` | bool | sí | **v2, nuevo**: **Siempre `false`, constante literal.** Reemplaza la ambigüedad de `physical_execution_performed` (que mezclaba "se ejecutó la colección de campo" con "se ejecutó control físico"); ahora son dos campos separados (`field_collection_executed` arriba sí puede ser `true`, este nunca). |

Los ocho campos en negrita son los invariantes read-only: el collector
los asigna como constantes `False` directamente en el código fuente
(`build_bundle`), nunca derivados de un comando, fixture o flag — ni un
fixture adversarial puede hacer que valgan `true`. Todos están en
`MUST_BE_FALSE_FIELDS` y el validador los re-verifica independientemente.

## p0_ros_graph.json

| Campo | Tipo | Semántica |
|---|---|---|
| `nodes` | list[string] | Nombres de `ros2 node list`. |
| `topics` | list[{name, type}] | De `ros2 topic list -t`. |
| `services` | list[{name, type}] | De `ros2 service list -t`. |
| `actions` | list[{name, type}] | De `ros2 action list -t`. |
| `critical_topics` | list[{name, type}] | Subconjunto de `topics` en `SENSOR_TOPICS ∪ CMD_VEL_TOPICS`. |
| `critical_actions` | list[{name, type}] | Copia de `actions` (toda acción descubierta se considera crítica de revisar). |

## p0_tf_and_localization.json

| Campo | Semántica |
|---|---|
| `tf_topic_present`, `tf_static_topic_present`, `odom_topic_present`, `map_topic_present`, `map_metadata_topic_present` | Presencia en `topics` del grafo. |
| `single_sample_tf_static`, `single_sample_odom` | Texto crudo de `ros2 topic echo --once`, o `null` si el topic no existe. |
| `candidate_odom_source`, `candidate_odom_type`, `candidate_odom_frame_id`, `candidate_child_frame_id` | Mejor esfuerzo extraído del sample de `/odom`; `null` si no hay sample. |
| `candidate_odom_frequency` | Reservado; `null` en esta fase (no se mide `hz` de `/odom` para evitar bloquear el preflight; ver `PREFLIGHT_PROXIMA_SESION_FISICA_ODOM_TF.md`). |
| `map_source`, `map_frame` | `/map`/`map` si `map_topic_present`, si no `null`. |
| `tf_edges_observed` | **v2, ya no reservado**: extraído del sample crudo de `/tf_static` mediante regex (`frame_id:`/`child_frame_id:` con negative-lookbehind para no confundir `frame_id` dentro de `child_frame_id`), emparejado posicionalmente en `"<parent>-><child>"`. |
| `required_tf_edges` | Constante: `["map->odom", "odom->base_link", "base_link->utlidar_lidar", "base_link->imu_link"]`. El validador exige que las 4 estén en `tf_edges_observed` para `GO_CANDIDATE`. |
| `l2_odometry`, `l3_localization_map` | `NOT_READY` o `CANDIDATE_OBSERVED_PENDING_ANALYSIS`. **Nunca** `READY` — ningún collector ni validador de esta fase promueve automáticamente a `READY`. |

## p0_sensors.json

`sensors`: objeto keyed por topic (`/scan`, `/utlidar/cloud`,
`/livox/imu`, `/camera/color/image_raw`, `/camera/depth/image_rect_raw`).
Cada valor:

| Campo | Semántica |
|---|---|
| `present` | `true` si el topic apareció en `ros2 topic list`. |
| `type` | De `ros2 topic info -v`, o `null`. |
| `publisher_count` | De `ros2 topic info -v`, o `null`. |
| `frequency_attempted` | `false` si el topic no está presente, o si su tipo es `PointCloud2` (para evitar volcar nubes de puntos completas o bloquear con `hz` sobre datos pesados). |
| `frequency_result` | Hz medido, o `null`. |
| `frame_id` | Reservado; `null` en esta fase. |
| `sample_collected` | Reservado; `false` en esta fase. |
| `errors` | `["NOT_DISCOVERED"]` si `present=false`; `[]` en caso contrario. |

Contrato de orden: nunca se ejecuta `ros2 topic hz`/`info` sobre un
topic que no apareció primero en `ros2 topic list` (verificado por
`test_p0_readonly_pipeline_e2e.py::TestMissingTopicFixture`).

## p0_cmd_vel_chain.json

`topics`: objeto keyed por `/cmd_vel`, `/cmd_vel_raw`, `/cmd_vel_safe`,
cada uno con `present`/`type`/`publisher_count`/`subscription_count`
(**v2, nuevos**, extraídos por regex de `topic info -v`)/`publishers`/
`subscribers`/`qos` (texto crudo de `topic info -v`, nunca se publica
nada).

| Campo | Semántica |
|---|---|
| `unexpected_global_cmd_vel` | `true` si `/cmd_vel` (el topic global, no namespaced) está presente. |
| `collision_monitor_observed`, `controller_server_observed` | `true` si algún nombre de nodo descubierto contiene esa subcadena. |
| `consumer_observed` | Reservado; `null`. |
| `status` | Constante: `"OBSERVED_PENDING_PHYSICAL_ANALYSIS"`. Nunca `"READY"` ni implica nada sobre seguridad física real. |

## p0_safety_human_checklist.json

**v2**: ningún campo humano tiene valor por defecto ni se infiere; todos
provienen de un flag de CLI explícito (o, en tests, de un override
explícito). Ausencia ⇒ el campo queda en su tipo "vacío" (`False`/`None`)
y el validador lo trata como NO_GO, nunca como GO implícito.

| Campo | Tipo | Para `GO_CANDIDATE` |
|---|---|---|
| `operator_present` | bool | debe ser `true` |
| `operator_identity_or_role` | string\|null | **v2**: debe ser texto no vacío (`--operator-role`); vacío/ausente ⇒ `OPERATOR_ROLE_MISSING_OR_EMPTY` (NO_GO) |
| `hardstop_present` | bool | debe ser `true` |
| `hardstop_type` | string\|null | **v2**: debe ser texto no vacío (`--hardstop-type`); vacío/ausente ⇒ `HARDSTOP_TYPE_MISSING_OR_EMPTY` (NO_GO) |
| `hardstop_tested_before_session` | bool | **v2**: debe ser literalmente `true` (`--hardstop-tested-before-session yes`); cualquier otro valor, incluido un histórico `"unknown"`, ⇒ `NO_GO` (ya no es solo una advertencia) |
| `area_cleared` | bool | debe ser `true` |
| `robot_physically_supervised` | bool | **v2**: debe declararse explícitamente (`--robot-physically-supervised yes`); ya **no** se infiere de `operator_present AND area_cleared` |
| `dual_control_prohibited_acknowledged` | bool | **v2**: debe ser `true`, declarado explícitamente (`--dual-control-prohibited-acknowledged yes`); ya no tiene default `true` |
| `movement_not_authorized_acknowledged` | bool | debe ser `true` |
| `notes` | string\|null | informativo |

## p0_command_log.json

`commands`: lista de entradas, una por comando (real o de fixture):

```json
{
  "label": "git_branch",
  "argv": ["git", "-C", "<repo>", "branch", "--show-current"],
  "started_utc": "...", "ended_utc": "...", "duration_ms": 12,
  "exit_code": 0, "timed_out": false,
  "stdout": "robot\n", "stderr": "",
  "stdout_truncated": false, "stderr_truncated": false,
  "read_only_classification": "read_only"
}
```

`stdout`/`stderr` se truncan a `COMMAND_OUTPUT_TRUNCATE_CHARS` (4000
caracteres); `stdout_truncated`/`stderr_truncated` indican si ocurrió.
Nunca se registran secretos (el collector no introspecciona variables
de entorno sensibles ni credenciales; las URLs de remotos Git se
redactan antes de persistirse).

**v2 — auditoría del command log por el validador** (independiente del
collector, nunca confía en su propia clasificación):

- cada `label` debe matchear uno de los patrones de
  `_ALLOWED_LABEL_PATTERNS` (regex anchorado: `git_*`, `ros2_*_list`,
  `tf_static_echo_once`, `odom_echo_once`, `topic_info_*`,
  `topic_hz_*`, `cmd_vel_info_*`);
- `argv` debe ser una lista de strings, no vacía, y no contener ninguna
  subcadena de `_FORBIDDEN_COMMAND_SUBSTRINGS` (`send_goal`, `topic
  pub`, `service call`, `lifecycle set`, `param set`, `launch`,
  `unitree`, `lowcmd`, `lowstate`, `sport_mode`, `loco`, `damp`,
  `stand`, `sit`, `walk`, `cmd_vel_published`, `nav_vel`);
- `read_only_classification` debe ser exactamente `"read_only"`;
- `exit_code` debe ser `int`, `timed_out` debe ser `bool`.

Capa separada `collection_completeness`: los comandos "estrictos"
(`git_branch`, `git_head`, `git_status`, `git_remote_origin`,
`ros2_node_list`, `ros2_topic_list`, `ros2_service_list`,
`ros2_action_list`) deben estar presentes, con `exit_code == 0` y
`timed_out == false`. Los comandos "acotados"
(`tf_static_echo_once`, `odom_echo_once`) pueden tener
`timed_out == true` solo si produjeron `stdout` no vacío; un timeout
sin evidencia parseable es un fallo de completitud, no de integridad
ni de invariantes read-only.

## p0_hash_manifest.json

```json
{
  "schema_version": 2, "session_id": "...", "collected_at_utc": "...",
  "collector_version": "2H.2.5",
  "files": [
    {
      "filename": "p0_session_meta.json", "sha256": "<64 hex>",
      "size_bytes": 1234, "file_type": "regular", "nlink": 1,
      "mode": "0o600", "uid": 1000
    }
  ]
}
```

**v2**: cada entrada incluye ahora metadata de filesystem (`file_type`,
`nlink`, `mode`, `uid`), no solo `sha256`/`size_bytes`. El validador
rechaza: nombres con separador de ruta o `..` (path traversal), nombres
duplicados, nombres no listados en `BUNDLE_DATA_FILES` (`MANIFEST_EXTRA_FILENAME`),
y archivos cubiertos por el manifest que falten en disco.

Cubre los 7 archivos de datos (nunca a sí mismo). El sidecar
`p0_hash_manifest.sha256` contiene el SHA-256 del propio manifest (una
línea de texto, formato `^[0-9a-f]{64}$` estrictamente validado),
escrito de forma atómica (`atomic_write_bytes`), para detectar si el
manifest mismo fue alterado. El validador rechaza un sidecar ausente,
con formato inválido, o cuyo hash no coincida con el manifest real en
disco.
