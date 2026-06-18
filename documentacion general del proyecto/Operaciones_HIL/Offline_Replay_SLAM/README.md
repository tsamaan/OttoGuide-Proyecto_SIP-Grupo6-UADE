# Offline Replay SLAM

Indice operativo para trabajo offline de replay, SLAM y sandbox Nav2 sin robot fisico.

## Documentos

| Documento | Uso |
|---|---|
| `RUNBOOK_REPLAY_ROSBAG_2026-06-04.md` | Replay local de rosbags HIL. |
| `OFFLINE_NAVIGATION_SANDBOX_PLAN_2026-06-10.md` | Plan de sandbox Nav2 offline sin hardware. |
| `NAV2_OFFLINE_SANDBOX_2026-06-10.md` | Evidencia y limites del sandbox offline. |

## Uso seguro

- Ejecutar solo con artifacts locales y `use_sim_time` cuando corresponda.
- No ejecutar Nav2 fisico ni publicar `/cmd_vel`.
- No afirmar mapa navegable a partir de mapa estacionario o TF sintetico.
- Requerir bags con `/scan`, `/tf`, `/tf_static` y fuente de odometria validada para pruebas representativas.

## Bloqueos actuales

- El artifact `20260618_081438` no contiene `/odom`, `/tf`, `/tf_static`, `/map` ni `/map_metadata` en runtime.
- El frame observado para `/scan` es `utlidar_lidar`, sin cadena TF confirmada hacia `base_link`.
- La fuente traslacional Unitree para `/odom` sigue pendiente de validacion HIL.
