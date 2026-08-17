# Reporte HIL Unitree HG State Probe - 2026-05-27

## Resultado Ejecutivo

Se ejecuto un probe C++ temporal estrictamente subscriber-only contra canales DDS HG del Unitree G1. El robot publico mensajes reales en los tres canales candidatos, sin usar publishers, clientes de control, ROS mapping ni comandos de movimiento.

Resultado para odometria: `usable_for_odom=AMBIGUOUS`. Los mensajes recibidos confirman IMU, joints y estado FSM, pero no se observaron campos de pose XY ni velocidad corporal necesarios para implementar `/odom` de forma defendible.

Decision: no implementar `odom_bridge` en esta sesion y no ejecutar mapeo.

## Baseline Git y Runtime

- Repositorio: `/home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE`
- Rama: `robot`
- HEAD inicial: `224df18`
- `origin/robot` inicial: `224df18`
- Ahead/behind inicial: `0 0`
- Tracked dirty inicial: ninguno.
- Untracked admitidos: `codigo ottoguide/logs/` y `codigo ottoguide/artifacts/`.
- Runtime prohibido antes del probe: ninguno detectado.
- Runtime prohibido despues del probe: ninguno detectado.

## SDK y Toolchain

- SDK root: `/home/unitree/unitree_sdk2`
- Biblioteca SDK: `/home/unitree/unitree_sdk2/lib/aarch64/libunitree_sdk2.a`
- Headers usados: `channel_factory.hpp`, `channel_subscriber.hpp`, `idl/hg/LowState_.hpp`, `idl/hg/IMUState_.hpp`, `idl/hg/SportModeState_.hpp`.
- Dependencias DDS existentes usadas: `/home/unitree/unitree_sdk2/thirdparty/include/ddscxx`, `libddscxx.so`, `libddsc.so`.
- Interfaz usada: `eth0` (solo seleccionada por `ChannelFactory`; no modificada).

## Probe Temporal Subscriber-Only

- Fuente temporal: `/tmp/ottoguide_unitree_hg_state_probe.cpp`
- Binario temporal: `/tmp/ottoguide_unitree_hg_state_probe`
- Duracion interna: 10 segundos.
- Wrapper de ejecucion: `timeout 15 /tmp/ottoguide_unitree_hg_state_probe eth0`.
- Check previo de patrones prohibidos: PASS; sin `ChannelPublisher`, `LocoClient`, `SportClient`, `LowCmd`, `lowcmd`, `user_lowcmd`, `arm_sdk`, `cmd_vel` ni comandos de movimiento.

Comando de compilacion efectivo:

```bash
g++ -std=c++17 \
  -I/home/unitree/unitree_sdk2/include \
  -I/home/unitree/unitree_sdk2/thirdparty/include \
  -I/home/unitree/unitree_sdk2/thirdparty/include/ddscxx \
  /tmp/ottoguide_unitree_hg_state_probe.cpp \
  -L/home/unitree/unitree_sdk2/lib/aarch64 \
  -L/home/unitree/unitree_sdk2/thirdparty/lib/aarch64 \
  -lunitree_sdk2 -lddscxx -lddsc -lpthread \
  -Wl,-rpath,/home/unitree/unitree_sdk2/thirdparty/lib/aarch64 \
  -o /tmp/ottoguide_unitree_hg_state_probe
```

## Canales y Mediciones

| Canal | Tipo DDS | Mensajes / 10 s | Frecuencia aproximada |
| --- | --- | ---: | ---: |
| `rt/lowstate` | `unitree_hg::msg::dds_::LowState_` | 10510 | 1052.628 Hz |
| `rt/secondary_imu` | `unitree_hg::msg::dds_::IMUState_` | 10510 | 1052.662 Hz |
| `rt/sportmodestate` | `unitree_hg::msg::dds_::SportModeState_` | 998 | 99.995 Hz |

## Campos Observados

- LowState: `tick=8978830`, `mode_machine=5`.
- LowState IMU quaternion: `[-0.914, 0.000, 0.403, 0.054]`.
- LowState IMU RPY: `[0.063, -0.828, -0.145]`.
- LowState gyro: `[-0.003, 0.006, -0.001]`.
- LowState accel: `[7.078, 0.288, 6.581]`.
- LowState motor 0 q/dq: `[-0.678, 0.020]`.
- LowState motor 1 q/dq: `[0.137, 0.004]`.
- Secondary IMU quaternion: `[0.988, 0.011, -0.149, 0.029]`.
- Secondary IMU RPY: `[0.014, -0.299, 0.056]`.
- Secondary IMU gyro: `[0.003, 0.010, 0.005]`.
- Secondary IMU accel: `[3.119, -0.083, 9.268]`.
- SportModeState: `fsm_mode=0`.

## Evaluacion Odom

- Pose XY disponible en los mensajes observados: NO.
- Velocidad corporal disponible en los mensajes observados: NO.
- IMU disponible: YES.
- Motores/joints disponibles: YES mediante `LowState_`.
- Estado FSM disponible: YES mediante `SportModeState_`.
- Fuente apta para `odom_bridge` ahora: NO.
- Clasificacion: `ODOM_SOURCE_AMBIGUOUS_IMU_ONLY` / `usable_for_odom=AMBIGUOUS`.

## Proxima Accion

Buscar un canal Unitree de pose o velocidad corporal real, o inspeccionar servicios/factory state ya presentes, siempre en modo read-only. No implementar `odom_bridge` hasta disponer de una fuente traslacional validada.

## Restricciones Respetadas

- Publishers creados: NO
- `ChannelPublisher` usado: NO
- `LocoClient` usado: NO
- `SportClient` usado: NO
- `LowCmd` usado: NO
- Comando de locomocion ejecutado: NO
- `/cmd_vel` publicado: NO
- Nav2 ejecutado: NO
- `scan_gate` ejecutado: NO
- `slam_toolbox` ejecutado: NO
- `map_saver_cli` ejecutado: NO
- Red modificada: NO
- Paquetes instalados: NO
- `git reset` ejecutado: NO
- `git clean` ejecutado: NO
- `git push` ejecutado: NO