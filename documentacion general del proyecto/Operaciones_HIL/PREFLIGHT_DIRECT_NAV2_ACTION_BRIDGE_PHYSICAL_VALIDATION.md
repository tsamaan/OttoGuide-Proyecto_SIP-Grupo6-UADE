# Preflight — DirectNav2ActionBridge, validación física futura

```text
OFFLINE_ONLY
NOT_FOR_HARDWARE_EXECUTION_YET
NOT_FOR_PHYSICAL_SAFETY_VALIDATION
PHYSICAL_NAVIGATION = NOT_READY
```

Este documento es un **handoff operativo**, no una validación. No autoriza,
programa ni ejecuta ningún paso sobre el robot físico. Fue creado durante la
Fase 2H.1.4, que es exclusivamente offline.

Reutiliza, sin copiar extensamente, los criterios de seguridad y
procedimiento ya establecidos en:

- [HIL_TESTING_PROTOCOL.md](HIL_TESTING_PROTOCOL.md) — secuencia de
  activación física, hardstop `L1+A`, prohibición de operación dual
  (control remoto + API), apagado seguro. Ese protocolo gobierna cualquier
  manipulación física del robot; este documento no lo reemplaza ni lo
  reescribe.
- [PREFLIGHT_PROXIMA_SESION_FISICA_ODOM_TF.md](PREFLIGHT_PROXIMA_SESION_FISICA_ODOM_TF.md) —
  preflight read-only ya definido para descubrir fuentes reales de TF/odom
  (`ROS_DISTRO=foxy`, `rmw_cyclonedds_cpp`, IPs `192.168.123.*`). La
  sección C de este documento es una extensión de ese mismo espíritu
  read-only, aplicada específicamente a `DirectNav2ActionBridge`.
- [Offline_Replay_SLAM/OFFLINE_NAVIGATION_SANDBOX_READINESS.md](Offline_Replay_SLAM/OFFLINE_NAVIGATION_SANDBOX_READINESS.md) —
  estado de readiness por nivel (`L0`–`L3`, `PHYSICAL_NAVIGATION`), que
  este documento hereda sin alterar.

## A. Estado actual

```text
DirectNav2ActionBridge        = aislado y validado offline (Fases 2H.1/2H.1.2/2H.1.3/2H.1.4/2H.1.5)
main.py / TourOrchestrator    = seleccionable via NAVIGATION_BACKEND=direct (Fase 2H.2)
MAIN_RUNTIME_MIGRATED         = NO (default ROBOT_MODE=real sigue en legacy)
LEGACY_NAVIGATION_RUNTIME_ACTIVE = YES (default sin cambio)
Fase 2H.2                     = completada (selector offline, runtime validation PASS — ver MAIN_RUNTIME_NAVIGATION_SELECTION_2H2_REPORT.md)
Fase 2H.2.1                   = completada (hardening fail-closed, tests, guards estáticos, smoke Popen — ver MAIN_RUNTIME_NAVIGATION_SELECTION_2H21_HARDENING_REPORT.md)
Fase 2H.2.2                   = implementada; evidencia incompleta, corregida por 2H.2.3 (ver MAIN_RUNTIME_NAVIGATION_SELECTION_2H22_HARDENING_REPORT.md)
Fase 2H.2.3                   = PARTIAL_SUPERSEDED_BY_2H24 (timeout hardening válido; pipeline P0 era skeleton no funcional end-to-end — ver MAIN_RUNTIME_NAVIGATION_SELECTION_2H23_EVIDENCE_CORRECTION_REPORT.md)
Fase 2H.2.4                   = IMPLEMENTED_PENDING_INDEPENDENT_AUDIT (TOCTOU de cleanup corregido, pipeline P0 funcional offline end-to-end, runtime declarado PARTIAL — ver MAIN_RUNTIME_NAVIGATION_SELECTION_2H24_P0_PIPELINE_REPORT.md)
P0_PHYSICAL_READ_ONLY         = PREPARED_NOT_AUTHORIZED / NOT_EXECUTED (tools/hil/physical_read_only/)
P1_P2_P3                      = NOT_AUTHORIZED
L2_ODOMETRY                   = NOT_READY
L3_LOCALIZATION_MAP           = NOT_READY
PHYSICAL_NAVIGATION           = NOT_READY
PHYSICAL_MOVEMENT             = NOT_AUTHORIZED
RAMA_OPERATIVA_VALIDADA       = robot
```

> **Nota 2H.2.3 (2026-06-22)**: la rama operativa validada es `robot` (no `main`).
> No hay "pendiente push a `main`". El candidato NO-GO de runtime de 2H.2.2 se
> registra como `CANDIDATE_RESOLVED_OFFLINE_PENDING_INDEPENDENT_AUDIT`. P0 es un
> paquete read-only preparado pero **no autorizado** y **no ejecutado**; P1/P2/P3
> permanecen `NOT_AUTHORIZED`. No se inspeccionó el robot en esta fase.
>
> **Nota 2H.2.4 (2026-06-22)**: el pipeline P0 (collector + bundle +
> manifest + validator) es ahora funcional offline de extremo a extremo
> (fixture mode probado, dry-run seguro); sigue **no autorizado** y **no
> ejecutado** contra el robot. La carrera TOCTOU del cleanup de grupos de
> proceso fue corregida y probada. La estabilidad runtime quedó
> `PARTIAL` (2 de 5 corridas con fallos de discovery/lifecycle-query no
> atribuibles a cambios de código, cleanup limpio en ambas). Ver el
> reporte 2H.2.4 para el detalle completo.

Toda la evidencia de `DirectNav2ActionBridge` recolectada hasta la Fase
2H.1.5 es exclusivamente contra `offline_runtime_simulator.py` (odometría
y scan sintéticos, ROS 2 Jazzy en WSL). Ninguna parte de esa evidencia se
transfiere automáticamente al robot físico, que corre `ROS_DISTRO=foxy`
con `rmw_cyclonedds_cpp` (ver `PREFLIGHT_PROXIMA_SESION_FISICA_ODOM_TF.md`).

## B. Bloqueos previos a cualquier movimiento (NO-GO)

Cada ítem es un bloqueo independiente. Ninguno se resuelve por inferencia
ni por analogía con el sandbox offline; cada uno requiere su propia
evidencia física.

```text
NO-GO 1: CANDIDATE_RESOLVED_OFFLINE_PENDING_INDEPENDENT_AUDIT — Fase 2H.2 (runtime validation), 2H.2.1 (hardening), 2H.2.2 (aislamiento/lease/identidad) y 2H.2.3 (corrección de evidencia: exit codes recapturados, FAIL_PREEXISTING_PROVEN contra baseline 82d4942, ruta de timeout del padre ejercitada en runtime, 3 corridas consecutivas 4/4). La rama operativa validada es `robot` (no `main`). Pendiente: auditoría independiente en otro chat. NO declarar COMPLETE/CLOSED/PHYSICAL_READY/P0_AUTHORIZED.
NO-GO 2: fuente física de odometría no validada (L2_ODOMETRY = NOT_READY)
NO-GO 3: TF física incompleta o no medida (map->odom, odom->base_link,
         base_link->utlidar_lidar; este último requiere extrínseco medido,
         no una identidad temporal)
NO-GO 4: mapa físico no validado para navegación (L3_LOCALIZATION_MAP = NOT_READY)
NO-GO 5: namespace/action names físicos no confirmados (el sandbox usa
         /offline_nav; el robot físico no tiene namespace confirmado todavía)
NO-GO 6: compatibilidad ROS 2 Foxy/Jazzy no resuelta (el robot corre Foxy +
         rmw_cyclonedds_cpp; DirectNav2ActionBridge solo fue ejercitado
         contra Jazzy + FastDDS en WSL)
NO-GO 7: Collision Monitor físico no verificado
NO-GO 8: cadena física cmd_vel_raw -> cmd_vel_safe no verificada
NO-GO 9: más de un propietario de locomoción (prohibición de operación
         dual ya establecida en HIL_TESTING_PROTOCOL.md, sección
         "Protocolo de Emergencia")
NO-GO 10: operador/hardstop ausente (L1+A debe estar disponible en mano
          antes de cualquier paso de las secciones P1-P3)
NO-GO 11: damp() no medido dentro del límite de tiempo esperado
```

Estos bloqueos quedan `PENDING_PHYSICAL_VALIDATION`. No bloquean el
trabajo offline de fases futuras (2H.2 puede diseñarse e implementarse
sin resolverlos), pero **ninguno** se resuelve por escritura de código ni
por este documento.

## C. Preflight read-only futuro

Comandos exclusivamente de lectura, a ejecutar en una sesión física futura
**después** de obtener autorización explícita y con operador/hardstop
presentes, siguiendo las condiciones de seguridad ya establecidas en
`PREFLIGHT_PROXIMA_SESION_FISICA_ODOM_TF.md` (prohibido publicar
`/cmd_vel`, prohibido ejecutar Nav2 físico, `stand`/`sit`/`walk`/`damp`).

```bash
# Identidad del repo desplegado
git branch --show-current
git rev-parse HEAD
git log -1 --format=%s

# Entorno ROS/DDS real
printenv ROS_DISTRO
printenv RMW_IMPLEMENTATION
printenv CYCLONEDDS_URI

# Grafo ROS real
ros2 node list
ros2 action list
ros2 action info /navigate_to_pose || true
ros2 action info /follow_waypoints || true
ros2 topic list

# Topics criticos (solo info, nunca echo de comandos de movimiento)
ros2 topic info /odom || true
ros2 topic info /tf || true
ros2 topic info /tf_static || true
ros2 topic info /map || true
ros2 topic info /scan || true

# Namespace y tipos reales de las acciones de navegacion
ros2 interface show nav2_msgs/action/NavigateToPose || true
ros2 interface show nav2_msgs/action/FollowWaypoints || true

# Publishers/subscribers reales de la cadena de velocidad
ros2 topic info /cmd_vel_raw || true
ros2 topic info /cmd_vel_safe || true
```

Explícitamente **prohibido** en esta sección (igual que en el preflight
ODOM/TF ya vigente):

```text
enviar goals NavigateToPose o FollowWaypoints
publicar /cmd_vel o cualquier topico de velocidad
ejecutar damp(), stand, sit, walk
activar Nav2 fisico
mover el robot de cualquier forma
```

## D. Matriz GO/NO-GO

```text
P0 — Inspeccion read-only
     Está preparado técnicamente (pipeline funcional offline desde
     Fase 2H.2.4: collector + bundle + manifest + validator, fixture
     mode probado end-to-end), pero NO está autorizado. Su ejecución
     real requiere TODO lo siguiente:
       1. auditoría independiente de Fase 2H.2.4;
       2. autorización explícita posterior;
       3. operador presente;
       4. hardstop presente;
       5. HEAD autorizado (--expected-head validado contra el commit
          publicado);
       6. sesión presencial controlada.
     Es la sección C de este documento.
     Estado: P0_PHYSICAL_READ_ONLY = PREPARED_NOT_AUTHORIZED / NOT_EXECUTED.

P1 — Compatibilidad de interfaces y configuracion
     Confirmar namespace real, ROS_DISTRO/RMW reales, tipos de accion
     reales, y reconciliar Foxy/Jazzy (NO-GO 6) antes de instanciar
     DirectNav2ActionBridge contra el robot.
     Estado: PENDING_PHYSICAL_VALIDATION.

P2 — Integracion main.py/bridge
     Exclusivamente despues de que las Fases 2H.2/2H.2.1/2H.2.2/2H.2.3 esten
     auditadas de forma independiente (NO-GO 1:
     CANDIDATE_RESOLVED_OFFLINE_PENDING_INDEPENDENT_AUDIT). La rama operativa
     validada es `robot`. No iniciar antes de la auditoria independiente.
     Estado: PENDING_PHYSICAL_VALIDATION / NOT_AUTHORIZED.

P3 — Prueba fisica acotada
     Exclusivamente con L2 (odometria) y L3 (localizacion/mapa)
     validados, y con la cadena de seguridad (Collision Monitor fisico,
     NO-GO 7/8) aprobada.
     Estado: PENDING_PHYSICAL_VALIDATION.
```

Ningún nivel P1–P3 puede declararse `READY` por este documento. Solo P0
queda preparado; su ejecución real y sus resultados son trabajo de una
sesión física futura, no de esta fase.

## E. Evidencia futura a guardar

Cuando se ejecute una sesión física (fuera del alcance de esta fase),
debe registrarse como mínimo:

```text
HEAD exacto del repo desplegado
ROS_DISTRO, RMW_IMPLEMENTATION, CYCLONEDDS_URI reales
lista completa de nodos, acciones y topicos descubiertos
tipos de mensaje/accion reales y su QoS
arbol TF completo observado
fuente de odometria identificada (nombre, tipo, frecuencia, semantica)
mapa fisico utilizado (si aplica) y su procedencia
namespace fisico real bajo el que corre el bridge
UUID del goal enviado
feedback recibido (conteo, contenido relevante)
respuesta real de CancelGoal (return_code, goals_canceling)
confirmacion de terminal CANCELED via result task observado
twist final (cero) y pose estable, con evidencia numerica
tiempo de damp() medido
PIDs/PGIDs de los procesos propios de la sesion
logs completos de la sesion, sin recortar
decision GO/NO-GO final, explicita y fechada
```

## F. Rollback futuro (definido, no ejecutado)

Esta secuencia se define para que exista antes de cualquier sesión física;
no se ejecuta en esta fase porque no hay sesión física en curso.

```text
1. no iniciar ningun movimiento nuevo
2. cancelar el goal activo via cancel_navigation()
3. si cancel_navigation() devuelve CANCEL_GOAL_HANDLE_UNAVAILABLE:
   - no asumir cancelacion
   - no enviar otro goal
   - mantener NO-GO
   - forzar la secuencia externa de seguridad solo cuando exista sesion
     fisica autorizada
   - cerrar bridge
   - preservar evidencia
4. esperar el terminal si es observable (result task presente)
5. si el terminal no es observable (CANCEL_TERMINAL_UNOBSERVABLE), asumir
   degradacion: no inferir CANCELED
6. forzar velocidad cero por el HAL fisico (no por el bridge)
7. ejecutar damp() como ya esta protocolizado en HIL_TESTING_PROTOCOL.md
8. cerrar el bridge (close()), aceptando que puede reportar
   DIRECT_BRIDGE_CLOSE_REMOTE_STATE_UNKNOWN si la degradacion es real
9. detener exclusivamente los procesos propios de la sesion (PIDs/PGIDs
   registrados en la seccion E), nunca por nombre ni con comodines
10. volver a la configuracion runtime previamente aceptada (AsyncNav2Bridge
    via main.py, sin DirectNav2ActionBridge conectado)
```

## Declaración final

Este documento no declara que el sistema esté listo para movimiento
físico. Declara únicamente qué debe verificarse, en qué orden, y qué
queda explícitamente prohibido hasta que cada bloqueo de la sección B se
resuelva con evidencia física real.
