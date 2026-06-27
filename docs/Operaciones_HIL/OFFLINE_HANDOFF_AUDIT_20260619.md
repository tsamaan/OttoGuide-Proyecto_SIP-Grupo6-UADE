# Auditoria offline del handoff fisico - capture bridge Unitree (2026-06-19)

Sesion 100% local. Sin SSH, sin conexion al robot, sin movimiento. Fuentes
usadas: repositorio local, mirror GitHub, archives del handoff fisico
(`artifacts/robot_handoff_20260619_123545/`), snapshot del SDK Unitree, WSL
(Ubuntu 24.04) para operaciones que requieren Linux real (AF_UNIX, ELF,
symlinks de colcon).

## 1. Hashes de los archives

| Archive | SHA256 | Verificacion |
|---|---|---|
| `ottoguide_robot_handoff_20260619_232511.tar.gz` | `f7d0d43b49046c3d051f4bf2be6836b630cebbdf935057fd300e42c993ad9aab` | Coincide Windows = `.sha256` remoto |
| `ottoguide_robot_sdk_20260619_232511.tar.gz` | `88c1e154efe41c2083754b43462f0bc35df9a416b3b2a0acfe76e74df88627fb` | Coincide Windows = `.sha256` remoto |

## 2. Extraccion en WSL y symlinks

Extraido dentro del filesystem Linux de WSL (`~/ottoguide_robot_handoff_20260619/`),
no sobre NTFS, para preservar los symlinks de colcon generados por
`colcon build --symlink-install`. La extraccion previa en Windows
(`artifacts/.../extracted/`) fallo parcialmente en 9 archivos dentro de
`build/ottoguide_unitree_capture_bridge/` por limitaciones de reparse points
de NTFS/`tar.exe` con symlinks absolutos — confirmado no critico, ya que
`repo_snapshot/` contiene el codigo fuente real en archivos planos con su
propio manifiesto de checksums.

Symlinks de colcon preservados en WSL (apuntan a rutas absolutas del robot,
esperado — el `build/` symlink-install enlaza al `ros2_ws/src` original):

```text
build/ottoguide_unitree_capture_bridge/launch/capture_bridge.launch.py -> .../ros2_ws/src/.../launch/capture_bridge.launch.py
build/ottoguide_unitree_capture_bridge/ottoguide_unitree_capture_bridge -> .../ros2_ws/src/.../ottoguide_unitree_capture_bridge
build/ottoguide_unitree_capture_bridge/package.xml -> .../ros2_ws/src/.../package.xml
build/ottoguide_unitree_capture_bridge/resource/... -> .../ros2_ws/src/.../resource/...
build/ottoguide_unitree_capture_bridge/setup.cfg -> .../ros2_ws/src/.../setup.cfg
build/ottoguide_unitree_capture_bridge/setup.py -> .../ros2_ws/src/.../setup.py
build/ottoguide_unitree_capture_bridge/share/... -> .../ros2_ws/build/.../share/...
```

## 3. Checksums internos

- `repo_snapshot/SHA256SUMS.txt`: 19/20 archivos coinciden exactamente
  (verificado por sufijo relativo, ya que el manifiesto fue generado con
  rutas absolutas del robot y no es portable literal). El unico "mismatch"
  es el propio `SHA256SUMS.txt`: el script original del handoff crea el
  archivo vacio (via redireccion `>`) antes de que `find` escanee el
  directorio, por lo que `find` lo incluye en su propio listado y termina
  hasheando una version incompleta de si mismo. Es un artefacto de orden de
  ejecucion del script de la sesion fisica anterior, no evidencia de
  alteracion de contenido.
- `sdk_metadata/SHA256SUMS.txt`: 56/56 archivos coinciden exactamente
  (headers C++, `libunitree_sdk2.a`, `libddsc.so`, `libddscxx.so`).

## 4. repo_snapshot vs Git (rama `robot`, HEAD `c35bf5e`)

`diff -ruN` (ignorando `__pycache__`/`*.pyc`) entre el snapshot recibido del
robot y el working tree actual, para:

- `codigo ottoguide/tools/hil/unitree_capture_bridge/`
- `codigo ottoguide/ros2_ws/src/ottoguide_unitree_capture_bridge/`
- `codigo ottoguide/tools/hil/ottoguide-map`
- `codigo ottoguide/tools/hil/analyze_capture_sqlite.py`
- los 3 documentos de `Operaciones_HIL/` incluidos en el handoff

**Resultado: 0 diferencias.** El robot, en el momento del cierre fisico,
estaba exactamente en el estado versionado en `c35bf5e` — no habia ningun
cambio local sin commitear en el robot que integrar.

## 5. Auditoria estatica del binario ARM64

Binario: `ottoguide_unitree_capture_tap` (preservado en
`build/ottoguide_unitree_capture_tap` dentro del archive liviano).

```text
file:    ELF 64-bit LSB pie executable, ARM aarch64, dynamically linked,
         interpreter /lib/ld-linux-aarch64.so.1, not stripped
RUNPATH: /home/unitree/unitree_sdk2/lib/aarch64:
         /home/unitree/unitree_sdk2/thirdparty/lib/aarch64
NEEDED:  libddscxx.so.0, libddsc.so.0, libpthread.so.0, libstdc++.so.6,
         libgcc_s.so.1, libc.so.6, ld-linux-aarch64.so.1
         (sin libunitree_sdk2.so -> el SDK esta linkeado estaticamente,
         no como dependencia dinamica)
```

Strings de canales DDS presentes: `rt/lowstate`, `rt/lf/lowstate`,
`rt/secondary_imu`, `rt/sportmodestate`. Ningun string `rt/api/*`.

Auditoria de tokens prohibidos (`ChannelPublisher|CreateSendChannel|
LocoClient|SportClient|LowCmd|ClientStub|SetVelocity|SetFsmId`) sobre la
tabla de simbolos (`readelf -Ws`, 21282 lineas) y sobre `strings` (13827
lineas): **0 coincidencias**. El simbolo `CreateRecvChannel<LowState_>` esta
presente, confirmando el patron subscriber-only. `libunitree_sdk2.a` (el
`.a` vendor completo) si contiene objetos `client_stub.cpp.o`,
`server_stub.cpp.o`, etc. — es codigo general del SDK, pero el linker no lo
incorporo al binario final (dead-code elimination), confirmado por la
ausencia de esos simbolos en el ELF resultante.

`build_on_robot.sh` es consistente con el binario auditado: mismo
`SDK_ROOT` (`/home/unitree/unitree_sdk2`), mismas rutas de include/lib,
mismo rpath, y contiene su propia auditoria embebida de tokens prohibidos
(la unica coincidencia del grep externo sobre `native/` es el propio
literal del patron dentro de ese script).

## 6. Cross-compilacion

`aarch64-linux-gnu-g++` no esta disponible en ninguna distribucion WSL local
(`Ubuntu` ni `Ubuntu-24.04`). `CROSS_BUILD_NOT_AVAILABLE` — no se intento
instalar el toolchain (fuera de alcance sin autorizacion explicita). No es
un fallo del proyecto; la unica compilacion valida del tap sigue siendo
`build_on_robot.sh` ejecutado en el propio robot ARM64.

## 7. SDK preservado

`sdk_snapshot/` (544 archivos totales, manifiesto propio) incluye headers
de `unitree/robot/channel`, `unitree/idl/hg`, `unitree_joystick.hpp`,
`CMakeLists.txt`, la libreria estatica `libunitree_sdk2.a` (132 objetos,
incluye locomocion vendor sin usar) y las librerias dinamicas CycloneDDS
(`libddsc.so`, `libddscxx.so`, ambas ELF AArch64). Headers completos de
`thirdparty/include/{ddsc,ddscxx,dds}` tambien preservados para referencia
offline. Todo verificado byte-a-byte contra `sdk_metadata/SHA256SUMS.txt`.

## 8. Grafo ROS en el momento del cierre

`ros2 daemon status`: not running. `ros2 topic list` con timeout de 8s:
sin respuesta (sin participantes DDS descubribles). Esto es consistente con
que el bridge/tap/rosbag ya estaban detenidos antes del cierre de la sesion
fisica (confirmado en la auditoria previa de esa misma sesion). No se
encontro ningun bag con topicos `/unitree/*` entre los 4 `metadata.yaml`
existentes en `artifacts/` del robot.

## 9. Que quedo probado en esta sesion offline

- Integridad completa del handoff (hashes externos + internos).
- Identidad exacta entre el snapshot del robot y Git (`c35bf5e`).
- Seguridad estatica del binario ARM64 y del codigo fuente (sin APIs de
  locomocion, sin publishers de control).
- `protocol.py` (parsing, validacion, capa de socket AF_UNIX) con 16
  aserciones nuevas verificadas sobre sockets reales en WSL/Linux —
  creacion, limpieza de socket stale, rechazo de archivo regular ocupando
  la ruta, multiples datagramas, tamano maximo, datagrama sobredimensionado,
  parse error sin corromper lecturas siguientes, patron de conteo de drops,
  shutdown limpio.
- El wrapper `unitree-capture-bridge`, con una bateria de 36 tests de shell
  (`test_source_ros.sh` 5, `test_safety_checks.sh` 17, `test_wrapper.sh` 14)
  contra `ros2`/`ip` falsos y procesos dummy propios — nunca contra el
  robot ni contra un proceso ajeno real.
- Un emisor sintetico IPC (`synthetic/synthetic_ipc_emitter.py`) que
  reproduce el protocolo version 1 exacto del tap, con 6 casos negativos
  verificados contra el parser real.

## 10. Bug critico encontrado y corregido: `fail()` fail-open bajo `if`

Durante la escritura de los tests de integracion del wrapper se detecto que
`fail()` (definida como `echo ... >&2; return 1`) dependia enteramente de
que `errexit` (`set -e`) propagara el abort hacia arriba desde sitios como
`assert_no_publishers /cmd_vel` (statement plano dentro de `cmd_start`).
Bash **suspende `errexit` en todo el scope dinamico de la condicion de un
`if`/`while`/`until`**, incluyendo llamadas a funciones y subshells
ejecutadas dentro de esa condicion. Cualquier invocador que envuelva el
wrapper en un patron tan natural como:

```bash
if unitree-capture-bridge start; then ...
```

neutralizaba en silencio **todos** los safety checks (`/cmd_vel`, `/odom`,
Nav2/SLAM, procesos foraneos) — `cmd_start` continuaba ejecutandose hasta
el final (incluyendo el spawn real del bridge y del tap) pese a haber
logueado un `[capture-bridge] ERROR: ...` por el camino. Se reprodujo el
bug de forma determinista (`attempt_start` reportaba exito con un publisher
`/cmd_vel` activo) y se corrigio cambiando `fail()` a `exit 1`, que termina
el proceso/subshell de forma incondicional sin depender de la semantica de
`errexit` dentro de condicionales. Las 36 pruebas de shell pasan luego del
fix; antes del fix, 9 de 14 casos de `test_wrapper.sh` fallaban exactamente
por este motivo.

## 11. Pendiente — requiere sesion fisica

- DDS real en domain 0 / eth0 (canales `rt/lowstate`, `rt/lf/lowstate`,
  `rt/secondary_imu`, `rt/sportmodestate`).
- Tasas reales de los 4 tipos de paquete.
- `wireless_remote` real desde `rt/lowstate`.
- Bridge end-to-end con datos reales del robot (solo validado con el
  emisor sintetico y con tests unitarios offline).
- Captura rosbag con topicos `/unitree/*` (no existe ninguna todavia).
- L1 con bag Unitree real, L2, L3 (sin cambios respecto al estado conocido
  previo: L0 validado con captura anterior, L1 pendiente de bag Unitree, L2
  y L3 no disponibles).

No se afirma en ningun punto de esta auditoria que el bridge funcione
end-to-end con datos reales del robot.
