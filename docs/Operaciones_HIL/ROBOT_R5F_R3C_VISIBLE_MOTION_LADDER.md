# ROBOT-R5F-R3C -- Escalera de movimiento visible calibrado

## Contexto

R5F-R3B valido `SetVelocity()`/`StopMove()` contra el robot real (wrapper v2), pero con
limites demasiado conservadores para producir desplazamiento visualmente confirmable
(~1.4 grados de giro, ~1.5 cm de desplazamiento lineal). Este checkpoint construye el
wrapper v3, que reemplaza esos modos unicos por una escalera de perfiles nombrados y
hardcodeados, escalada bajo confirmacion separada del operador en cada nivel.

## Wrapper v3

Fuente: `codigo ottoguide/tools/hil/robot_motion/ottoguide_g1_motion_v3.cpp`
Build: `codigo ottoguide/tools/hil/robot_motion/build_g1_motion_v3.sh`

Modos: `status` (default, read-only), `passive-damp`, `velocity-stop`, `yaw-l1`, `yaw-l2`,
`yaw-l3`, `yaw-return-l1`, `yaw-return-l2`, `linear-l1`, `linear-l2`, `linear-l3`.

Ningun modo acepta vx/omega/duration por CLI -- son constantes hardcodeadas seleccionadas
solo por `--mode`. `Damp()` permanece aislado en `passive-damp`, nunca llamado implicitamente.
Todo perfil de movimiento cierra con `StopMove()`.

| Perfil | omega/vx | duration | magnitud esperada |
|---|---|---|---|
| yaw-l1 | +0.20 rad/s | 0.50s | ~5.7 grados |
| yaw-l2 | +0.30 rad/s | 0.60s | ~10.3 grados |
| yaw-l3 | +0.45 rad/s | 0.60s | ~15.5 grados |
| linear-l1 | +0.10 m/s | 0.50s | ~5 cm |
| linear-l2 | +0.20 m/s | 0.60s | ~12 cm |
| linear-l3 | +0.30 m/s | 0.60s | ~18 cm |

## Resultados de validacion real (ROBOT-R5F-R3C, companion 192.168.123.164)

- `status`: exitoso, `fsm_id=501`.
- `yaw-l1`: `SetVelocity()`/`StopMove()` retornaron 0. **Giro visible y estable** confirmado
  por el operador en el primer nivel evaluado. No se requirio yaw-l2/l3.
- `yaw-return-l1`: ejecutado opcionalmente para revertir el giro. Ambas legs retornaron 0,
  robot estable.
- `linear-l1`: exito de API, sin desplazamiento visible.
- `linear-l2`: exito de API, **desplazamiento visible y estable** confirmado por el operador.
  No se requirio linear-l3.

Ningun nivel produjo anomalia, caida o inestabilidad. `Damp()` no fue llamado en ningun
momento; `StopMove()` fue el cierre normal de las 5 llamadas de movimiento de la sesion.

## Perfiles de referencia recomendados

Para movimiento visible minimo confirmado en este robot/superficie: **yaw-l1** (giro) y
**linear-l2** (desplazamiento lineal). yaw-l3 y linear-l3 quedan disponibles en el binario
como techo, pero no fueron necesarios ni ejecutados en esta sesion.

Ver evidencia completa en el RUN_DIR de ROBOT-R5F-R3C
(`ROBOT_R5F_R3C_FINAL_REPORT.md`, `ROBOT_R5F_R3C_FINAL_STATE.json`).
