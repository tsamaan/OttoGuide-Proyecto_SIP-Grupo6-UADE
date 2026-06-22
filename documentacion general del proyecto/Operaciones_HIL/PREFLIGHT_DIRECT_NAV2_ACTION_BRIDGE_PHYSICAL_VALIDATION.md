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
Fase 2H.2.2                   = completada (aislamiento de proceso, lease criptográfico, identidad de kernel, escalada fail-closed — ver MAIN_RUNTIME_NAVIGATION_SELECTION_2H22_HARDENING_REPORT.md)
L2_ODOMETRY                   = NOT_READY
L3_LOCALIZATION_MAP           = NOT_READY
PHYSICAL_NAVIGATION           = NOT_READY
```

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
NO-GO 1: RESOLVED_OFFLINE — Fase 2H.2 completada (runtime validation PASS, 2026-06-22), Fase 2H.2.1 completada (hardening PASS, 2026-06-22) y Fase 2H.2.2 completada (aislamiento/lease/identidad PASS, 2026-06-22). Pendiente: push a main y auditoría de chat principal.
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
     Puede prepararse y ejecutarse ahora (sin mover el robot), siempre
     bajo las condiciones de seguridad de HIL_TESTING_PROTOCOL.md y con
     operador/hardstop presentes. Es la sección C de este documento.
     Estado: PENDING_PHYSICAL_VALIDATION (preparado, no ejecutado).

P1 — Compatibilidad de interfaces y configuracion
     Confirmar namespace real, ROS_DISTRO/RMW reales, tipos de accion
     reales, y reconciliar Foxy/Jazzy (NO-GO 6) antes de instanciar
     DirectNav2ActionBridge contra el robot.
     Estado: PENDING_PHYSICAL_VALIDATION.

P2 — Integracion main.py/bridge
     Exclusivamente despues de que la Fase 2H.2 y 2H.2.1 esten
     completadas y auditadas (NO-GO 1: RESOLVED_OFFLINE). No iniciar
     antes de confirmacion via chat principal y push a main.
     Estado: PENDING_PHYSICAL_VALIDATION.

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
