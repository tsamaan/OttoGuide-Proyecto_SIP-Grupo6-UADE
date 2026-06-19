# Runbook proxima sesion fisica - capture bridge Unitree (subscriber-only)

Sesion corta y dirigida. No repetir la auditoria completa del SDK (ya
quedo cubierta offline, ver `OFFLINE_HANDOFF_AUDIT_20260619.md`). No hacer
barrido de dominios DDS (domain 0 es obligatorio y ya esta fijado en el
codigo y en el wrapper). No iniciar navegacion, SLAM ni movimiento.

Pre-requisito: el robot debe estar en `c35bf5e` o mas adelante en la rama
`robot` antes de empezar (los cambios offline de esta sesion — wrapper
endurecido, banco sintetico, tests — todavia no fueron pusheados/llevados
al robot hasta que se confirme el push canonico; ver paso 0).

## 0. Llevar los cambios offline al robot

Si esta sesion offline ya pusheo a `origin/robot`, actualizar el robot por
bundle o `git pull` segun el procedimiento estandar del proyecto antes de
continuar. Confirmar:

```bash
cd /home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE
git rev-parse HEAD
git status --short --branch --untracked-files=all
```

Esperado: HEAD igual al nuevo HEAD de `robot` en `origin`, working tree
limpio (los logs viejos de Livox/MID360 untracked en `codigo ottoguide/logs/`
no son parte de esto y pueden seguir presentes).

## 1. Validar HEAD

```bash
git log --oneline -3
```

Confirmar que aparecen los commits de hardening del wrapper, el banco
sintetico y los tests offline.

## 2. Build

```bash
cd "/home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE/codigo ottoguide"
./tools/hil/unitree_capture_bridge/scripts/unitree-capture-bridge build
```

Esperado: `STATIC_BUILD_OK=/tmp/ottoguide_unitree_capture_tap`, sin
`NATIVE_SAFETY_AUDIT_FAILED` ni `UNEXPECTED_DYNAMIC_UNITREE_DEPENDENCY`.
`ros2 pkg executables ottoguide_unitree_capture_bridge` debe listar
`bridge_node`.

Hard stop si: el build falla, o el audit embebido en `build_on_robot.sh`
detecta algun token prohibido.

## 3. Plan

```bash
./tools/hil/unitree_capture_bridge/scripts/unitree-capture-bridge plan
```

Solo debe imprimir el plan. Confirmar visualmente: domain 0, interfaz
`eth0`, los 4 canales DDS esperados, el socket IPC, los 6 topicos del
allowlist. Ningun proceso debe iniciarse (verificar con
`pgrep -af ottoguide_unitree_capture` antes y despues: debe seguir vacio).

## 4. Start bridge

```bash
./tools/hil/unitree_capture_bridge/scripts/unitree-capture-bridge start
```

Esperado: `[capture-bridge] started bridge=<pid> tap=<pid>`.

Hard stop inmediato si aparece cualquiera de:

- `ERROR: /cmd_vel has`
- `ERROR: /odom has`
- `ERROR: ... publisher query failed`
- `ERROR: Nav2 or SLAM process detected`
- `ERROR: foreign or stale bridge process detected` (puede aparecer como
  `foreign tap process detected` / `foreign bridge process detected` con
  el wrapper endurecido)
- `ERROR: bridge did not create IPC socket`
- `ERROR: native tap exited during startup`

Si alguno aparece: **no reintentar automaticamente**. Investigar la causa
exacta antes de continuar (el wrapper ya no enmascara estos casos detras de
`errexit` silencioso — ver seccion 10 de la auditoria offline para el
porque).

## 5. Validate bridge

```bash
./tools/hil/unitree_capture_bridge/scripts/unitree-capture-bridge validate
```

Esperado: `CAPTURE_BRIDGE_VALIDATE_PASS`. Si falla con
`MISSING_TOPIC=...`, esperar unos segundos (discovery DDS) y reintentar una
vez antes de tratarlo como fallo real.

## 6. Comprobar los seis topicos

```bash
ros2 topic list | grep '^/unitree/'
```

Esperado, exactamente estos seis, ni mas ni menos:

```text
/unitree/remote_joy
/unitree/lowstate_imu
/unitree/secondary_imu
/unitree/fsm_state
/unitree/lowstate_summary
/unitree/sdk_health
```

## 7. Medir tasas

```bash
for t in remote_joy lowstate_imu secondary_imu fsm_state lowstate_summary sdk_health; do
  echo "=== /unitree/$t ==="
  timeout 5 ros2 topic hz "/unitree/$t" || true
done
```

Esperado aproximado: `lowstate_imu`/`remote_joy` ~50 Hz, `secondary_imu`
~100 Hz, `fsm_state` ~10 Hz (solo si `rt/sportmodestate` esta publicando),
`sdk_health` ~1 Hz. Registrar los valores reales obtenidos en la bitacora
de esta sesion (no en este runbook).

## 8. Status final de seguridad

```bash
./tools/hil/unitree_capture_bridge/scripts/unitree-capture-bridge status
```

Confirmar `CMD_VEL_STATUS=SAFE_ZERO_PUBLISHERS` y
`ODOM_STATUS=SAFE_ZERO_PUBLISHERS`. Cualquier `UNKNOWN_*` o
`UNSAFE_ACTIVE_PUBLISHERS:*` es un hard stop — no continuar con sensores ni
con `ottoguide-map` hasta resolverlo.

## 9. Preparar sensor stack

Seguir el procedimiento ya validado en sesiones anteriores
(`RUNBOOK_LIVOX_SDK2_BRIDGE.md`, documentos previos de aislamiento del
sensor stack). No alterado por esta sesion offline.

## 10. `ottoguide-map plan`

```bash
./tools/hil/ottoguide-map plan
```

Confirmar que el plan incluye los topicos `/unitree/*` junto con
`/utlidar/cloud`, `/livox/imu`, `/scan` antes de grabar.

## 11. Bag estacionario de 10 segundos

```bash
./tools/hil/ottoguide-map start
sleep 10
./tools/hil/ottoguide-map stop
./tools/hil/ottoguide-map finalize
```

Robot **estacionario** durante toda la captura. No mover, no caminar, no
usar el control remoto para locomocion (el remote_joy se captura pasivamente
de todas formas).

## 12. Analyzer

```bash
python3 tools/hil/analyze_capture_sqlite.py <ruta_del_bag_db3>
```

Esperado: `L0 sensors: READY`, `L1 intention: READY` (si el bag contiene
`/unitree/remote_joy` con gaps <= 1s), `L2`/`L3`: `NOT READY` (esperado,
sin `/odom` ni `/tf`/`/map` todavia).

Este es el primer bag con topicos `/unitree/*` del proyecto — guardar su
ruta para referencia futura.

## 13. Stop bridge

```bash
./tools/hil/unitree_capture_bridge/scripts/unitree-capture-bridge stop
```

Esperado: `tap stopped`, `bridge stopped`, socket IPC removido. Confirmar:

```bash
pgrep -af 'ottoguide_unitree_capture_tap|ottoguide_unitree_capture_bridge'
```

Debe no imprimir nada.

## 14. Copiar artifact

Repetir el procedimiento de handoff liviano ya usado en la sesion del
2026-06-19 (archive + sha256 + scp + verificacion de hash en Windows) para
el nuevo bag y para cualquier log generado. No es necesario repetir el
snapshot completo del SDK si no cambio.

## Hard stops (recordatorio)

```text
aparece publisher /cmd_vel
aparece publisher /odom
se inicia Nav2 o SLAM
se produce movimiento
un proceso foraneo no identificado aparece como tap o bridge
CMD_VEL_STATUS o ODOM_STATUS distinto de SAFE_ZERO_PUBLISHERS
```
