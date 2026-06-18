# ODOM/TF Offline Analysis — OttoGuide

## 1. Fuente analizada

| Campo | Valor |
|---|---|
| Artifact auditado | `artifacts/_audit/ottoguide_odom_tf_audit_20260618_081438.tar.gz` |
| SHA256 esperado | `DB0C2CC33AB77FBEC4B056EABE9551B32D9BC5F16680920689FE92FE9F295AA5` |
| SHA256 observado | `DB0C2CC33AB77FBEC4B056EABE9551B32D9BC5F16680920689FE92FE9F295AA5` (coincide) |
| Commit canónico analizado | `2b7fc5c` (`docs(hil): add movement technical baseline document`) |
| Repo canónico | `https://github.com/tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE.git` (rama `robot`) |
| Fecha de análisis offline | 2026-06-18 |

Archivos principales revisados dentro del artifact:

- `ODOM_TF_NEXT_STEPS.md`
- `critical_topics_info.txt`
- `ros_graph_overview.txt`
- `cyclonedds_configs.txt`
- `repo_files_tf_odom_candidates.txt`
- `topic_candidates_odom_tf_state.txt`
- `processes_tf_odom_candidates.txt`
- `grep_tf_odom_references.txt` (muestra del repo versionado)

Documentación histórica HIL complementaria (sesiones físicas previas, no revalidadas hoy):

- `documentacion general del proyecto/Historico/Operaciones_HIL_Reportes/REPORTE_HIL_ODOM_TF_AUDIT_20260526.md`
- `documentacion general del proyecto/Historico/Operaciones_HIL_Reportes/REPORTE_HIL_UNITREE_HG_STATE_PROBE_20260527.md`
- `documentacion general del proyecto/Historico/Operaciones_HIL_Reportes/REPORTE_HIL_ODOM_BRIDGE_TIMED_MAPPING_20260527.md`

## 2. Estado runtime observado en la última sesión física

Evidencia del artifact `20260618_081438` (robot sentado, `scan_gate.launch.py` activo, sin locomoción):

| Categoría | Observación |
|---|---|
| `ROS_DISTRO` | `foxy` |
| `RMW_IMPLEMENTATION` | `rmw_cyclonedds_cpp` |
| `CYCLONEDDS_URI` | `file://.../codigo ottoguide/config/cyclonedds.foxy.xml` |
| Topics presentes | `/utlidar/cloud`, `/livox/imu`, `/scan`, `/parameter_events`, `/rosout` |
| Topics faltantes | `/tf`, `/tf_static`, `/odom`, `/map`, `/map_metadata`, `/cmd_vel`, `/joint_states`, `/robot_description` |
| Nodos activos | `livox_sdk_bridge_node`, `pointcloud_to_laserscan` |
| Frame sensor en `/scan` | `utlidar_lidar` |
| DDS peers configurados | `192.168.123.161`, `192.168.123.164` (locomotion controller candidato; no validado como fuente `/odom` ROS) |

Riesgo técnico:

- Sin `/tf` ni `/odom`, Nav2, AMCL y SLAM en movimiento quedan bloqueados.
- El `/scan` publicado usa `frame_id=utlidar_lidar` sin cadena TF hacia `base_link`/`odom`.
- No hay evidencia en este artifact de topics ROS `LowState`/`SportModeState`; los canales DDS HG (`rt/lowstate`, `rt/sportmodestate`) fueron observados en sesión previa vía probe C++ subscriber-only, pero **no** como topics ROS ni como odometría traslacional.
- **No hay navegación autónoma validada. No hay mapa navegable confirmado. No hay Nav2 físico listo para operar.**

## 3. Lectura de ODOM_TF_NEXT_STEPS.md

### Hallazgos

- Clasificación del artifact: `ODOM/TF PARTIAL SOURCE FOUND`.
- Sensores raw activos confirmados; pipeline Livox → pointcloud → laserscan operativo.
- Paquetes/configs de SLAM/Nav2/TF existen en el repo, pero no hay publicadores runtime de TF/odom.
- Peer DDS `192.168.123.161` responde en red, pero no expone `/odom` en el grafo ROS 2 observado.
- URDF/Xacro usable para G1: **0** encontrados en el barrido del artifact; `robot_state_publisher` pendiente de validación.

### Acciones recomendadas (offline, seguras)

1. Diseñar TF estático mínimo `base_link` → `utlidar_lidar` (valores conservadores, pendiente medición física).
2. Preparar launch de `static_transform_publisher` deshabilitado por defecto o bajo flag explícito de diagnóstico.
3. Documentar contrato del futuro `odom_bridge` sin implementación física.
4. Preparar replay offline con rosbags existentes + TF sintético estacionario solo para pipeline/RViz.
5. En próxima sesión física: probe pasivo de canales DDS HG y búsqueda de topic traslacional antes de cualquier bridge.

### Bloqueos

- No se identificó fuente ROS activa de odometría en la sesión `20260618`.
- Probe histórico HG (`20260527`) confirmó IMU/joints/FSM pero **no** pose XY ni velocidad corporal.
- Calibración real `base_link` ↔ LiDAR y validación dinámica requieren sesión física supervisada.

## 4. Referencias Unitree

### LowState (`unitree_hg::msg::dds_::LowState_`)

- Canal DDS histórico observado: `rt/lowstate` (~1050 Hz en probe `20260527`).
- Campos útiles: IMU (quat, RPY, gyro, accel), estados de 35 motores, `tick`, `mode_machine`.
- **No** expone pose XY ni twist corporal en la evidencia revisada.
- Uso potencial offline: orientación aproximada, diagnóstico de joints; **no** odometría traslacional por sí solo.

### HighState / SportModeState

- `SportModeState_` HG en `rt/sportmodestate` (~100 Hz): expone `fsm_mode`, no pose.
- Documentación `ROS2_INTEGRATION.md` menciona `/sportmodestate` como `unitree_go::msg::SportModeState` vía bridge ROS; **no confirmado** en runtime del artifact `20260618`.
- Para G1, IDL correcto es `unitree_hg`, no `unitree_go`.

### Otros candidatos

| Candidato | Estado en artifact 20260618 | Notas |
|---|---|---|
| `rt/secondary_imu` / `IMUState_` | No en grafo ROS; histórico DDS sí | Solo orientación/inercia |
| `/odom` ROS | Ausente | — |
| `Odometer_service` / SVO | Histórico en repo, no runtime | Sin publicación `/odom` confirmada |
| Locomotion controller peer `.161` | Peer DDS configurado | Hipótesis: podría existir estado no bridged a ROS |

### Qué datos podrían servir para odometría (hipótesis, no validado)

- Integración inercial de IMU + joints: solo con modelo cinemático y calibración; riesgo alto de drift en humanoide.
- Canal Unitree no descubierto aún con pose/twist corporal (prioridad en próxima sesión read-only).
- SLAM scan-matching offline como camino paralelo para mapas diagnósticos, no para navegación física.

### Qué datos no deben asumirse

- Que `LowState` o `SportModeState` provean `/odom` usable sin validación traslacional.
- Que TF temporal identidad (sesión `20260526`) represente geometría real del robot.
- Que mapas estacionarios con TF temporal sean navegables.
- Que peers DDS impliquen topics ROS publicados.

## 5. TF mínimo propuesto

**Diseño conservador — no es validación física.**

```text
map  -->  odom           (futuro: SLAM/localization; no físico todavía)
odom  -->  base_link     (futuro: bridge dinámico desde estado Unitree o SLAM)
base_link  -->  utlidar_lidar   (static; extrínseco pendiente de medición real)
base_link  -->  imu_link        (opcional; confirmar frame de /livox/imu)
```

Parámetros iniciales sugeridos para trabajo offline (placeholder):

- `base_frame` en `slam_toolbox_mapping.yaml`: ya usa `base_link`.
- `utlidar_lidar` permanece como `frame_id` de `/scan` hasta medir montaje.
- Para replay estacionario diagnóstico: TF identidad temporal **solo** con etiquetado explícito de no-navegación (patrón ya usado en `REPORTE_HIL_ODOM_TF_AUDIT_20260526`).

## 6. Bridge Unitree state → nav_msgs/Odometry

| Aspecto | Propuesta |
|---|---|
| Entrada candidata (prioridad) | Canal DDS HG con pose/twist corporal si se descubre en sesión física; secundario: fusión IMU+joints solo tras modelado |
| Entrada histórica descartada por ahora | `rt/lowstate`, `rt/sportmodestate` solos (sin componente traslacional observada) |
| Salida candidata | `nav_msgs/msg/Odometry` en `/odom`, `child_frame_id=base_link`, `header.frame_id=odom` |
| Frecuencia esperada | 20–50 Hz publicación ROS si fuente DDS ≥100 Hz; throttling configurable |
| Covarianzas | Diagonal conservadora alta en x/y hasta calibración; orientación desde IMU con incertidumbre explícita |
| Modo de implementación | Nodo ROS 2 separado, **deshabilitado por defecto**, sin publishers hasta flag `OTTOGUIDE_ENABLE_ODOM_BRIDGE=1` en sesión autorizada |
| Riesgos | Drift, frames incorrectos, falsa confianza en Nav2, publicación accidental durante reposo |
| Criterios mínimos de aceptación offline | Contrato de mensaje documentado, tests unitarios de conversión con fixtures, `assert_no_cmd_vel_publishers.sh` en CI local, sin ejecución en robot |

**Estado actual: bridge no implementado. No publicar `/odom` en sesión offline.**

## 7. Replay/SLAM offline

### Qué se puede probar sin robot

- `codigo ottoguide/tools/hil/replay_rosbag_local.sh` sobre bags en `artifacts/` o `codigo ottoguide/logs/bags/`.
- RViz con configs en `codigo ottoguide/tools/hil/rviz/` (replay 2D, cloud, offline sandbox).
- `codigo ottoguide/tools/hil/nav2_offline_smoke_test.sh` y sandbox en `documentacion general del proyecto/Operaciones_HIL/Offline_Replay_SLAM/NAV2_OFFLINE_SANDBOX_2026-06-10.md`.
- Analisis de mapas con `codigo ottoguide/tools/hil/analyze_map_yaml.py`.
- Inspeccion del artifact ODOM/TF: `codigo ottoguide/scripts/audit/inspect_odom_tf_audit.sh`.

### Qué bags/artifacts hacen falta

- Bags con `/scan` + `/tf` + `/tf_static` para replay representativo (varios manifests históricos listan `/tf_static` pero sesión `20260618` no tenía TF).
- Bag de mapeo en movimiento con odometría real: **no disponible / no validado**.
- Mapa estacionario diagnóstico existente: `codigo ottoguide/maps/hil_stationary_slam_temp_tf_seated_20260527_030251.{yaml,pgm}` — **not usable for navigation**.

### Comandos seguros (offline, sin robot)

```bash
# Inspección del artifact (solo lectura)
bash "codigo ottoguide/scripts/audit/inspect_odom_tf_audit.sh"

# Info de bag local (requiere ROS 2 en Linux/WSL)
ros2 bag info artifacts/handoff_offline_20260604/rosbags/hil_mapping_stationary_retry_20260605_070755

# Replay con clock simulado (sin publicar cmd_vel)
bash "codigo ottoguide/tools/hil/replay_rosbag_local.sh" <bag_dir>
```

### Qué queda bloqueado hasta sesión física

- Validar topics DDS/ROS de estado traslacional.
- Medir extrínseco `base_link` → `utlidar_lidar`.
- Publicar TF/odom dinámico en runtime real.
- SLAM en movimiento y mapa navegable.
- Cualquier prueba Nav2 que envíe `/cmd_vel` al hardware.

## 8. Preflight próxima sesión física

Checklist seguro antes de conectar al robot:

- [ ] `git status` limpio; `HEAD` = `origin/robot` canónico.
- [ ] `ROS_DISTRO=foxy`, `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`.
- [ ] `CYCLONEDDS_URI` apunta a `codigo ottoguide/config/cyclonedds.foxy.xml` (validar con script existente).
- [ ] `ros2 topic list` — confirmar `/scan`, ausencia/presencia de `/tf`, `/odom`.
- [ ] `ros2 topic info /scan` — verificar `frame_id`.
- [ ] Robot sentado/parado, entorno supervisado, **locomoción prohibida** hasta autorización explícita.
- [ ] No ejecutar `ottoguide-map start`, Nav2 bringup ni publicar `/cmd_vel`.
- [ ] Primer paso sugerido: `bash codigo\ ottoguide/tools/hil/physical_mapping_status.sh` o `ros2 topic hz /scan` (solo lectura).

Condiciones para **no** avanzar:

- Drift o frames TF no reproducibles.
- Fuente de odometría traslacional no identificada.
- Scan con mayoría de `inf` sin explicación (artifact: 703/723 rangos `inf` en muestra).
- Cualquier comando que mueva el robot sin autorización humana.

## 9. Conclusión

### Qué se puede avanzar ahora (offline)

- Mantener este análisis y el script de inspección del artifact.
- Diseñar TF mínimo y contrato del `odom_bridge` sin implementación física.
- Continuar replay/RViz/QA de mapas estacionarios con etiquetado de no-navegación.
- Preparar launch esqueleto de static TF bajo flag de diagnóstico.

### Qué no se puede afirmar todavía

- Navegación autónoma validada.
- Mapa navegable confirmado.
- Nav2 físico listo para operar.
- Disponibilidad runtime de `/odom`, `/tf` o topics Unitree HG en ROS 2.
- Que el peer `192.168.123.161` provea odometría usable sin bridge adicional.

## 10. Actualizacion post-sync GitOps 2026-06-18

Se releyo el artifact local `artifacts/_audit/ottoguide_odom_tf_audit_20260618_081438.tar.gz` despues de sincronizar el mirror y limpiar remotos locales.

Resultado:

- SHA256 observado: `DB0C2CC33AB77FBEC4B056EABE9551B32D9BC5F16680920689FE92FE9F295AA5` (coincide con el esperado).
- `ros_graph_overview.txt` confirma nuevamente `/livox/imu`, `/scan` y `/utlidar/cloud`; no confirma `/odom`, `/tf`, `/tf_static`, `/map` ni `/map_metadata`.
- `topic_candidates_odom_tf_state.txt` solo lista `/livox/imu`.
- `processes_tf_odom_candidates.txt` muestra `scan_gate.launch.py`, `livox_sdk_bridge_node` y `pointcloud_to_laserscan`; no muestra nodo activo de odometria o TF.
- `unitree_sdk_state_references.txt` contiene referencias amplias de DDS/Unitree, pero no evidencia runtime ROS de pose XY o twist corporal.

Decision:

- Mantener el `odom_bridge` como contrato futuro, no implementado ni activado.
- Preparar la siguiente sesion fisica como preflight read-only centrado en descubrir fuente real de odometria y medir extrinsecos.
- Usar `Offline_Replay_SLAM/README.md`, `Replay_RViz/README.md` y `PREFLIGHT_PROXIMA_SESION_FISICA_ODOM_TF.md` como puntos de entrada.

## 11. Contrato offline del futuro odom_bridge

El contrato formal vive en `documentacion general del proyecto/Arquitectura/ODOM_BRIDGE_CONTRACT.md`.

Resumen:

- Define condiciones futuras para publicar `/odom` como `nav_msgs/msg/Odometry`.
- Rechaza `LowState`, `SportModeState`, IMU sola, joints solos, TF identidad temporal y mapa estacionario como odometria traslacional por si solos.
- Requiere fuente con pose XY/yaw o twist corporal validable, flags explicitos y covarianzas conservadoras.
- No implementa publicacion runtime, no inicializa ROS 2, no habilita navegacion fisica y no publica `/cmd_vel`.
