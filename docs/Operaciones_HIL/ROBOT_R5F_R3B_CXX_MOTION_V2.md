# ROBOT-R5F-R3B -- Wrapper C++ v2 de movimiento G1 (StopMove como cierre normal)

## Objetivo

Extender el wrapper minimo de R5F-R2 (`ottoguide_g1_micro_motion.cpp`) corrigiendo un
problema de diseno identificado por observacion fisica directa del operador: `Damp()` no debe
tratarse como "mantener parado" -- si el robot ya esta de pie, `Damp()` puede aflojar
articulaciones y hacer que se siente o caiga en el lugar. R5F-R3B introduce
`ottoguide_g1_motion_v2.cpp`, que separa `Damp()` en un modo explicito y aislado
(`passive-damp`), y usa `StopMove()` como cierre normal de todo comando de velocidad.

## Diferencias frente a v1 (R5F-R2)

- Modo por defecto: `status` (read-only), no `stop`.
- `--mode=status`: consultas de solo lectura (`GetFsmId`, `GetFsmMode`, `GetBalanceMode`,
  `GetStandHeight`). Sin movimiento, sin Damp, sin SetVelocity.
- `Damp()` aislado en `--mode=passive-damp`, nunca invocado implicitamente por otro modo.
- `--mode=velocity-stop`: `StopMove()` solo -- cierre normal de cualquier comando de
  velocidad, o parada de emergencia segura tras una anomalia.
- `--mode=stand-up` y `--mode=balance-stand` agregados como modos explicitos e
  independientes.
- `micro-yaw` y `linear-min` cambiados: cierran con `StopMove()`, no con `Damp()`.
- `--mode=micro-yaw-return` agregado: par de yaw positivo/negativo acotado para volver
  aproximadamente a la orientacion inicial.
- Limites hardcodeados identicos en espiritu a v1 (duracion <= 0.30s, magnitudes
  conservadoras), no configurables por CLI.

## Validacion fisica real (R5F-R3B)

Ejecutado contra el robot real (companion 192.168.123.164, interfaz `eth0`) tras un cambio de
bateria, con el robot confirmado de pie estable por el operador:

- `--mode=status`: exitoso. `GetFsmId()` retorno 0 con `fsm_id=501` (consistente con FSM de
  pie/locomocion activa). `GetFsmMode()` retorno 0. `GetBalanceMode()`/`GetStandHeight()`
  retornaron codigo 7301 (`LocoState not available`) -- limitacion de datos, no fallo de
  canal.
- `--mode=micro-yaw` (omega=+0.08 rad/s, 0.30s): `SetVelocity()` y `StopMove()` retornaron 0.
  Sin anomalia fisica, pero el operador no pudo confirmar visualmente el movimiento por su
  magnitud pequena.
- `--mode=linear-min` (vx=+0.05 m/s, 0.30s): mismo resultado -- comandos exitosos, robot
  estable, desplazamiento no visualmente confirmable.
- `--mode=passive-damp`, `--mode=stand-up`, `--mode=balance-stand`,
  `--mode=micro-yaw-return`: implementados pero no ejecutados en esta sesion (no fueron
  necesarios: el robot ya estaba de pie estable, y el operador salteo BalanceStand y
  micro-yaw-return).

## Build

```bash
./build_g1_motion_v2.sh [output_path]
```

Mismos requisitos que v1: SDK de Unitree instalado (`/opt/unitree_robotics` por defecto,
override via `OTTOGUIDE_UNITREE_SDK_ROOT`). Compilado sin sudo, sin instalar dependencias
nuevas.

## Limitaciones y proximo paso

Los limites actuales (0.08 rad/s para yaw, 0.05 m/s para desplazamiento lineal, ambos con
duracion de 0.30s) son deliberadamente conservadores pero producen movimiento demasiado
pequeno para confirmacion visual directa. Un futuro checkpoint deberia disenar y validar
explicitamente limites mayores (mayor duracion y/o magnitud), partiendo de este wrapper v2
como base, en vez de asumir que los valores actuales son definitivos.

## Nota sobre el reloj del companion

Durante R5F-R3B se detecto que el reloj del sistema del companion mostraba 1970-06-12 en vez
de la fecha real, consistente con un reset de RTC tras el cambio de bateria. Esto no bloqueo
la sesion (la red funcionaba con normalidad) pero afecta los timestamps de archivos generados
en el companion durante esta sesion -- las decisiones de movimiento se basaron en la salida
en vivo de los comandos y en confirmacion directa del operador, no en timestamps de archivo.
