# Runbook proxima sesion fisica - OttoGuide DDS Foxy

## 1. Estado actual versionado

- Branch: `robot`
- HEAD local/remoto: `31bc27d`
- Ultimo commit: `chore(hil): add Foxy CycloneDDS validation candidate`
- Archivos agregados:
  - `codigo ottoguide/config/cyclonedds.foxy.xml`
  - `codigo ottoguide/scripts/validate_cyclonedds_config.sh`
- Archivos runtime no modificados:
  - `codigo ottoguide/config/cyclonedds.xml`
  - `codigo ottoguide/cyclonedds.xml`
  - `codigo ottoguide/scripts/start_robot.sh`
  - `codigo ottoguide/scripts/preflight_check.sh`
  - `codigo ottoguide/scripts/preflight_sensors.sh`
  - `codigo ottoguide/scripts/hil_start_mapping.sh`

## 2. Estado fisico conocido al cierre anterior

- Robot HEAD al cierre: `0bd81eb`
- Remoto/local luego del cierre: `31bc27d`
- eth0: `192.168.123.164/24`
- ruta interna: `192.168.123.0/24 dev eth0 src 192.168.123.164`
- Notebook Windows: `192.168.123.101`
- Locomotion/control Unitree: `192.168.123.161`
- Livox MID360: `192.168.123.120`
- Candidato descartado por ahora: `192.168.123.20`
- RealSense: Intel RealSense D435i detectada por `lsusb`, `/dev/video0` a `/dev/video5`, `/dev/media0` a `/dev/media2`
- procesos: no quedaron procesos ROS/Livox/Nav2/SLAM peligrosos al cierre
- bundle offline: `artifacts/robot_final_session_20260603_175751/ottoguide_final_session_20260603_175751.tar.gz`

## 3. Riesgo principal

El archivo versionado `codigo ottoguide/config/cyclonedds.xml` fallo en ROS 2 Foxy/CycloneDDS del robot con:

```text
config: //CycloneDDS/Domain/General: Interfaces: unknown element
file: codigo ottoguide/config/cyclonedds.xml
```

La construccion sospechosa es:

```xml
<Interfaces>
  <NetworkInterface name="eth0" />
</Interfaces>
```

El candidato `codigo ottoguide/config/cyclonedds.foxy.xml` usa la forma legacy:

```xml
<NetworkInterfaceAddress>eth0</NetworkInterfaceAddress>
```

Ese candidato todavia no fue validado fisicamente en el robot. No reemplazar `config/cyclonedds.xml` hasta tener una validacion exitosa.

## 4. Preparacion al conectar el robot

Comandos Windows:

```powershell
$ErrorActionPreference = "Stop"
cd "C:\Users\lucas\Documents\OttoGuide-Proyecto_SIP-Grupo6-UADE"

git status --short --branch --untracked-files=all
git rev-parse --short HEAD
git rev-parse --short target-uade/robot
git rev-list --left-right --count HEAD...target-uade/robot
git log --oneline -5

$sshKey = "$env:USERPROFILE\.ssh\id_ed25519_ottoguide_robot"
ssh -i $sshKey `
  -o ConnectTimeout=10 `
  -o ServerAliveInterval=15 `
  -o ServerAliveCountMax=2 `
  unitree@192.168.123.164 `
  "hostname; whoami; date"
```

Validar Git y red en robot:

```powershell
ssh -i $sshKey `
  -o ConnectTimeout=10 `
  -o ServerAliveInterval=15 `
  -o ServerAliveCountMax=2 `
  unitree@192.168.123.164 `
  "cd /home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE && git status --short --branch --untracked-files=all && git rev-parse --short HEAD && git rev-list --left-right --count HEAD...origin/robot"

ssh -i $sshKey `
  -o ConnectTimeout=10 `
  -o ServerAliveInterval=15 `
  -o ServerAliveCountMax=2 `
  unitree@192.168.123.164 `
  "ip -br addr show eth0; ip route | grep '192.168.123.0/24'; ip neigh show | grep -E '192\.168\.123\.(101|120|161|20)' || true"
```

## 5. Actualizar robot a 31bc27d si sigue en 0bd81eb

No hacer push desde el robot. No usar merge no fast-forward. No borrar untracked.

```bash
cd "/home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE"

git status --short --branch --untracked-files=all
git diff --name-only
git diff --cached --name-only
git remote -v
```

Elegir el remoto existente que apunte a:

```text
https://github.com/tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE.git
```

Luego:

```bash
REMOTE="origin"

timeout 45 git fetch --prune "$REMOTE" robot

git rev-parse --short HEAD
git rev-parse --short FETCH_HEAD
git rev-list --left-right --count HEAD...FETCH_HEAD
```

Aplicar fast-forward solo si el resultado es `0 N` y no hay cambios tracked:

```bash
git merge --ff-only FETCH_HEAD

git status --short --branch --untracked-files=all
git rev-parse --short HEAD
git rev-list --left-right --count HEAD...origin/robot
git log --oneline -5
```

Criterio esperado:

```text
HEAD robot = 31bc27d
origin/robot = 31bc27d
ahead/behind = 0 0
tracked changes = empty
untracked logs/artifacts preservados
```

Usar credenciales solo si GitHub las pide. Si Git pide credenciales y no estan disponibles, detener y preparar actualizacion offline por patch/bundle.

## 6. Validar CycloneDDS Foxy candidato

Comando exacto, sin drivers:

```bash
cd "/home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE"

bash "codigo ottoguide/scripts/validate_cyclonedds_config.sh" \
  "/home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE/codigo ottoguide/config/cyclonedds.foxy.xml"
```

Este script solo debe:

- exportar `ROS_DOMAIN_ID=0`
- exportar `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`
- exportar `CYCLONEDDS_URI=file://.../cyclonedds.foxy.xml`
- sourcear `/opt/ros/foxy/setup.bash`
- ejecutar `timeout 8 ros2 topic list`
- ejecutar `ros2 daemon stop`

## 7. Interpretacion

- exit 0: el XML candidato es aceptado por ROS 2 Foxy/CycloneDDS del robot.
- exit no cero: conservar stdout/stderr; no reemplazar XML ni tocar runtime.
- evidencia a guardar:
  - salida completa del script
  - `echo "$CYCLONEDDS_URI"`
  - `ros2 daemon status`
  - `ros2 daemon stop`
  - `sha256sum codigo\ ottoguide/config/cyclonedds.foxy.xml`
  - `sha256sum codigo\ ottoguide/config/cyclonedds.xml`
  - `sed -n '1,220p' "$HOME/cyclonedds_ws/cyclonedds.xml"` si existe

## 8. Hard stops

- eth0 no es `192.168.123.164/24`
- `192.168.123.0/24` no va por eth0
- Livox `.120` no responde
- aparecen procesos ROS/Livox/Nav2/SLAM inesperados
- git tiene cambios tracked
- validacion DDS falla por XML
- SSH inestable
- Git pide merge no fast-forward
- aparece `192.168.123.20` como unica ruta candidata sin nueva evidencia fuerte

## 9. Que NO ejecutar

- `ros2 launch`
- `ros2 run` de drivers
- Nav2
- SLAM
- `slam_toolbox`
- `map_saver`
- `/cmd_vel`
- `SportClient`
- `LocoClient`
- `LowCmd`
- `ChannelPublisher`
- `apt update`
- `apt install`
- `pip install`
- `git reset`
- `git clean`
- cambios de red
- cambios DDS persistentes
- cambios Livox persistentes

## 10. Si valida OK

Proponer, no ejecutar en el mismo paso:

- actualizar scripts para apuntar a `cyclonedds.foxy.xml`, o
- reemplazar `config/cyclonedds.xml` despues de una segunda validacion controlada, o
- mantener ambos XMLs y seleccionar explicitamente por variable `CYCLONEDDS_URI` en runbooks HIL.

Antes de cualquier driver:

```bash
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="file:///home/unitree/Desktop/Ottoguide/OttoGuide-Proyecto_SIP-Grupo6-UADE/codigo ottoguide/config/cyclonedds.foxy.xml"

set +u
source /opt/ros/foxy/setup.bash
set -u

ros2 daemon status || true
ros2 daemon stop || true
```

## 11. Si falla

- conservar stderr/stdout completo
- no reemplazar XML
- no modificar `config/cyclonedds.xml`
- no modificar `~/.bashrc`
- capturar version/paquetes:

```bash
dpkg -l | grep -E 'ros-foxy-cyclonedds|ros-foxy-rmw-cyclonedds|cyclonedds'
```

- comparar con home XML:

```bash
if [ -f "$HOME/cyclonedds_ws/cyclonedds.xml" ]; then
  sha256sum "$HOME/cyclonedds_ws/cyclonedds.xml"
  sed -n '1,220p' "$HOME/cyclonedds_ws/cyclonedds.xml"
fi
```

- volver a analisis offline con la evidencia.

## 12. Checklist final

- [ ] SSH estable a `unitree@192.168.123.164`
- [ ] robot en branch `robot`
- [ ] robot actualizado a `31bc27d`
- [ ] tracked changes vacio
- [ ] untracked logs/artifacts preservados
- [ ] eth0 en `192.168.123.164/24`
- [ ] ruta `192.168.123.0/24` por eth0
- [ ] Livox `.120` responde
- [ ] `.20` sigue descartado salvo evidencia nueva
- [ ] `validate_cyclonedds_config.sh` ejecutado sin drivers
- [ ] `ros2 daemon stop` ejecutado al cierre
- [ ] no Nav2/SLAM/drivers/locomocion
