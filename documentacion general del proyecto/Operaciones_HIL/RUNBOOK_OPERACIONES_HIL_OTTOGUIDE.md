# Runbook Operaciones HIL OttoGuide

## 1. Proposito y alcance

Este documento consolida el estado operativo HIL vigente para OttoGuide sobre Unitree G1 EDU 8. No reemplaza los reportes historicos: los resume como evidencia y define la ruta segura para la siguiente sesion fisica.

Prioridad operativa:

```text
seguridad fisica > no locomocion > no tocar red/IPs > no lanzar drivers persistentes > evidencia reproducible
```

## 2. Estado actual del repo

- Branch vigente: `robot`
- HEAD local/remoto vigente: `31bc27d`
- Commit vigente: `chore(hil): add Foxy CycloneDDS validation candidate`
- Robot al cierre fisico anterior: `0bd81eb`
- Accion requerida en proxima sesion fisica: actualizar robot a `31bc27d` por fast-forward si sigue en `0bd81eb`.
- Artifacts locales no versionados preservados: `artifacts/robot_final_session_20260603_175751/...`

## 3. Red fisica validada

| Componente | Valor vigente |
|---|---|
| Robot / Companion PC | `192.168.123.164` |
| Interfaz critica | `eth0` |
| eth0 robot | `192.168.123.164/24` |
| Ruta critica | `192.168.123.0/24 dev eth0 src 192.168.123.164` |
| Notebook Windows | `192.168.123.101` |
| Locomotion/control Unitree | `192.168.123.161` |
| Livox MID360 confirmado | `192.168.123.120` |
| Candidato descartado por ahora | `192.168.123.20` |
| USB tether observado | `usb1 10.21.209.158/24`, no requerido para HIL DDS local |

No cambiar IPs ni pasar Livox a `.20` sin nueva evidencia fisica fuerte.

## 4. SSH y acceso

Key funcional Windows:

```powershell
$sshKey = "$env:USERPROFILE\.ssh\id_ed25519_ottoguide_robot"
```

Prueba minima:

```powershell
ssh -i $sshKey `
  -o ConnectTimeout=10 `
  -o ServerAliveInterval=15 `
  -o ServerAliveCountMax=2 `
  unitree@192.168.123.164 `
  "hostname; whoami; date"
```

Hard stop si SSH es inestable, cambia host key o no responde.

## 5. GitOps para robot

Validacion local:

```powershell
cd "C:\Users\lucas\Documents\OttoGuide-Proyecto_SIP-Grupo6-UADE"
git status --short --branch --untracked-files=all
git rev-parse --short HEAD
git rev-parse --short target-uade/robot
git rev-list --left-right --count HEAD...target-uade/robot
```

Actualizacion robot si sigue en `0bd81eb`:

```bash
cd "/home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE"
git status --short --branch --untracked-files=all
git diff --name-only
git diff --cached --name-only
git remote -v

REMOTE="origin"
timeout 45 git fetch --prune "$REMOTE" robot
git rev-parse --short HEAD
git rev-parse --short FETCH_HEAD
git rev-list --left-right --count HEAD...FETCH_HEAD
git merge --ff-only FETCH_HEAD
```

No usar `reset`, `clean`, `stash`, merge no fast-forward ni push desde robot.

## 6. DDS / CycloneDDS

Hallazgo vigente:

```text
codigo ottoguide/config/cyclonedds.xml fallo en Foxy:
//CycloneDDS/Domain/General: Interfaces: unknown element
```

Archivos DDS:

| Archivo | Estado |
|---|---|
| `codigo ottoguide/config/cyclonedds.xml` | runtime actual, fallo con `Interfaces` en Foxy |
| `codigo ottoguide/config/cyclonedds.foxy.xml` | candidato nuevo, pendiente validacion fisica |
| `codigo ottoguide/cyclonedds.xml` | alternativo/historico, no fija `eth0` |
| `~/cyclonedds_ws/cyclonedds.xml` | usado por `~/.bashrc`, usa `AllowMulticast=spdp` |

Valores a preservar:

```text
ROS_DOMAIN_ID=0
RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
eth0
AllowMulticast=false para la ruta candidata versionada
peers minimos: 192.168.123.161, 192.168.123.164
peer historico a revisar: 192.168.123.100
```

## 7. Validacion DDS Foxy

Comando exacto, sin drivers:

```bash
cd "/home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE"

bash "codigo ottoguide/scripts/validate_cyclonedds_config.sh" \
  "/home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE/codigo ottoguide/config/cyclonedds.foxy.xml"
```

Interpretacion:

- exit `0`: el XML candidato es aceptado por ROS 2 Foxy/CycloneDDS.
- exit no cero: conservar stderr/stdout, no reemplazar XML, volver a analisis offline.

## 8. Livox MID360

Config vigente:

```text
codigo ottoguide/config/livox/mid360_sdk2_bridge.json
host_ip=192.168.123.164
lidar_ip=192.168.123.120
multicast_ip=224.1.1.5
```

Validacion pasiva permitida:

```bash
ping -c 2 -W 1 192.168.123.120
ip neigh show | grep -E '192\.168\.123\.(120|20)' || true
```

No ejecutar drivers Livox hasta resolver DDS y preflight.

## 9. RealSense

Evidencia fisica anterior:

```text
Intel RealSense D435i detectada por lsusb
/dev/video0 a /dev/video5 presentes
/dev/media0 a /dev/media2 presentes
v4l2-ctl no instalado
rs-enumerate-devices no instalado
```

No lanzar `realsense2_camera` hasta completar preflight DDS y confirmar no procesos peligrosos.

## 10. Preflight sin locomocion

Antes de cualquier prueba:

```bash
pgrep -afi 'ros2|roscore|rosmaster|nav2|slam|livox|realsense|scan_gate|svo|cmd_vel|sport|loco|lowcmd' || true
ip -br addr show eth0
ip route | grep '192.168.123.0/24'
```

No ejecutar `ros2 launch`, `ros2 run` de drivers, Nav2, SLAM, SVO ni `/cmd_vel` durante preflight DDS.

## 11. Proxima sesion fisica

Secuencia recomendada:

1. Confirmar SSH.
2. Confirmar red `eth0`.
3. Confirmar Git robot y actualizar a `31bc27d` si falta.
4. Confirmar tracked clean.
5. Validar `cyclonedds.foxy.xml`.
6. Guardar stdout/stderr.
7. Ejecutar `ros2 daemon stop`.
8. Cerrar sin drivers si DDS falla.

Ver detalle en:

```text
documentacion general del proyecto/Operaciones_HIL/RUNBOOK_PROXIMA_SESION_FISICA_DDS_FOXY.md
```

## 12. Hard stops

- eth0 no es `192.168.123.164/24`
- `192.168.123.0/24` no va por eth0
- Livox `.120` no responde
- Git tiene cambios tracked
- robot no puede actualizarse por fast-forward
- validacion DDS falla por XML
- aparecen procesos ROS/Livox/Nav2/SLAM inesperados
- SSH inestable
- GitHub pide credenciales no disponibles

## 13. Que NO ejecutar

- locomocion
- `/cmd_vel`
- `SportClient`, `LocoClient`, `LowCmd`, `ChannelPublisher`
- `ros2 launch`
- `ros2 run` de drivers
- Livox driver persistente
- RealSense driver persistente
- Nav2
- SLAM / `slam_toolbox`
- SVO / Odometer_service / UnitreeSlam / LIO-SAM
- `apt`, `pip`, `rosdep`
- cambios de red
- cambios DDS persistentes
- `git reset`, `git clean`, `git stash`

## 14. Historico de decisiones

- `scan_gate` y `slam_toolbox` tuvieron pruebas estacionarias previas, pero los mapas resultantes no son aptos para navegacion.
- No se encontro fuente activa ROS de `/odom`, `/tf` ni `/tf_static` durante auditorias previas.
- DDS Unitree `rt/lowstate`, `rt/secondary_imu` y `rt/sportmodestate` aportan estado/IMU/FSM, pero no pose XY ni velocidad corporal validada.
- SVO/Odometer_service es candidato historico, no ejecutado como fuente de navegacion.
- Livox `.120` queda como IP vigente; `.20` queda descartado hasta nueva evidencia.
- El XML DDS versionado fallo por sintaxis en Foxy; se agrego `cyclonedds.foxy.xml` como candidato.

## 15. Fuentes consolidadas

- `HIL_TESTING_PROTOCOL.md`: fases HIL, seguridad fisica, emergency stop, despliegue air-gapped.
- `PREFLIGHT_CERTIFICACION_SENSORES_PENDING.md`: criterios de sensores, topicos y frecuencias esperadas.
- `README_codigo_ottoguide.md`: arquitectura general, topologia de carpetas, pipeline HIL.
- `RUNBOOK_STARTUP_RC1.md`: secuencia RC1 y GO/NO-GO.
- `RUNBOOK_LIVOX_SDK2_BRIDGE.md`: configuracion y validacion Livox SDK2.
- `RUNBOOK_PACKET_CAPTURE_HIL.md`: captura pasiva y analisis Wireshark.
- `RUNBOOK_PROXIMA_SESION_FISICA_DDS_FOXY.md`: siguiente ventana fisica DDS Foxy.
- `Historico/Operaciones_HIL_Reportes/REPORTE_HIL_*`: evidencia historica de scan gate, odom/TF, Unitree DDS, Odometer_service, SVO y SDK probes.
- `ARQUITECTURA_OPERATIVA_RC1.md`, `ROS2_INTEGRATION.md`, `MEMORIA_ARQUITECTONICA_MVP.md`: marco arquitectonico vigente.
- `AppPhone/*`, `Historico/*`, `Hardware_Reference/*`: contexto secundario/historico.

## 16. Historico preservado

Los reportes `Historico/Operaciones_HIL_Reportes/REPORTE_HIL_*` no deben borrarse ni reescribirse: son bitacoras de evidencia por fecha. Los documentos AppPhone/Unitree Go/Explore y factory plane `192.168.12.x` quedan como investigacion secundaria; la ruta vigente para OttoGuide sigue siendo SDK2/DDS en `192.168.123.x`.

## 17. Checklist final

- [ ] SSH estable
- [ ] Git robot en `31bc27d`
- [ ] tracked clean
- [ ] untracked logs/artifacts preservados
- [ ] eth0 en `192.168.123.164/24`
- [ ] ruta interna por eth0
- [ ] Livox `.120` responde
- [ ] `.20` no se usa
- [ ] DDS Foxy validado sin drivers
- [ ] daemon ROS detenido al cierre
- [ ] no locomocion
