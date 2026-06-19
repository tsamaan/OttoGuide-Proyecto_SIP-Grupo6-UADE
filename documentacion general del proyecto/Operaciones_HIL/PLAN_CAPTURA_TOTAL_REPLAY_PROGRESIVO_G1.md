# Plan de captura total y replay progresivo â€” Unitree G1 EDU 8

**Proyecto:** OttoGuide
**Robot objetivo:** Unitree G1 EDU 8
**Sensor validado:** Livox MID360
**Fecha:** 2026-06-19
**Branch:** `robot`
**Estado:** preparaciÃ³n local previa a captura de recorrido humano

---

## Objetivo

Preparar una captura de recorrido humano (teach-by-walking con control remoto) que sirva para tres niveles independientes de replay:

| Nivel | Nombre | Requisito mÃ­nimo |
|-------|--------|-----------------|
| L1 | Teach-and-replay temporal | LiDAR + IMU + scan, timestamps continuos |
| L2 | Replay por estado SDK / odometrÃ­a candidata | SDK state (sportmodestate/lowstate) o /odom |
| L3 | LocalizaciÃ³n / SLAM / navegaciÃ³n nativa | /tf, /tf_static, /map |

**Principio:** no bloquear por TF/odom perfecto. Capturar todo lo disponible. Avanzar por nivel.

---

## Niveles

### Nivel 1 â€” Teach-and-replay temporal

**Concepto:** grabar la sesiÃ³n completa de recorrido humano con timestamp ROS. Reproducir el bag y ejecutar los mismos comandos en tiempo real (wall-clock synchronized playback).

**Requisitos:**
- `/utlidar/cloud` â€” PointCloud2 del MID360 (1480 Hz validado)
- `/livox/imu` â€” IMU del MID360 (200 Hz validado)
- `/scan` â€” LaserScan filtrado del scan_gate (1453 Hz validado)
- Timestamps continuos sin gaps > 1 s

**Limitaciones:** el robot no tiene estado propio de posiciÃ³n; la repeticiÃ³n depende del entorno no cambiando y del timing reproducible.

**Herramienta:** `ros2 bag play --rate 1.0 <bag_dir>`

---

### Nivel 2 â€” Replay por estado SDK / odometrÃ­a candidata

**Concepto:** usar los topics de estado del G1 SDK para estimar la trayectoria durante el recorrido humano y reproducirla mediante estado, no solo timing.

**Topics candidatos G1 DDS (no confirmados en runtime â€” descubrir con `plan` mode):**

| Topic | DescripciÃ³n | Candidato DDS |
|-------|-------------|---------------|
| `/sportmodestate` | Estado del modo sport (velocidades, IMU, posiciÃ³n pie) | SÃ­ |
| `/lf/sportmodestate` | Variante low-frequency | SÃ­ |
| `/lowstate` | Estado articular completo | SÃ­ |
| `/rt/lowstate` | Variante real-time | SÃ­ |
| `/rt/odommodestate` | OdometrÃ­a nativa del SDK | SÃ­ |
| `/rt/secondary_imu` | IMU secundaria interna | SÃ­ |
| `/wirelesscontroller` | Estado del control remoto | SÃ­ |
| `/odom` | OdometrÃ­a estÃ¡ndar ROS 2 | Candidato |

**MÃ©todo:** si alguno de estos topics existe en runtime, se captura automÃ¡ticamente con `ottoguide-map start`. El analyzer offline los detecta y reporta.

**Herramienta:** `analyze_capture_sqlite.py` clasifica y reporta `L2_odom_sdk` readiness.

---

### Nivel 3 â€” LocalizaciÃ³n / SLAM / navegaciÃ³n nativa

**Concepto:** usar /tf + /tf_static + /map para localizaciÃ³n continua del robot durante replay, habilitando navegaciÃ³n con Nav2 o SLAM toolbox.

**Requisitos:**
- `/tf` y `/tf_static` presentes y publicados
- `/map` o SLAM activo
- SLAM toolbox o Nav2 stack disponible

**Estado actual:** ninguno de estos topics estaba en la captura stationary (confirmado). La captura de recorrido humano debe intentar capturarlos si aparecen.

**Herramienta:** `ros2 run slam_toolbox localization_slam` (post-captura) o `nav2_map_server map_saver_cli`.

---

## Topics prioritarios

| Topic candidato | Prioridad | Uso esperado | Tipo | Bloquea si falta |
|----------------|-----------|-------------|------|-----------------|
| `/utlidar/cloud` | CRÃTICO | Nube de puntos LiDAR | sensor | SÃ­ (L1) |
| `/livox/imu` | CRÃTICO | IMU MID360 | sensor | SÃ­ (L1) |
| `/scan` | CRÃTICO | LaserScan filtrado | sensor | SÃ­ (L1) |
| `/tf` | ALTO | Transform tree | nav | No (L3 solo) |
| `/tf_static` | ALTO | TF estÃ¡tico | nav | No (L3 solo) |
| `/odom` | ALTO | OdometrÃ­a ROS | nav/estado | No (L2 degradado) |
| `/sportmodestate` | ALTO | Estado SDK sport | estado SDK | No (L2) |
| `/lf/sportmodestate` | ALTO | Estado SDK LF | estado SDK | No (L2) |
| `/lowstate` | MEDIO | Estado articular | estado SDK | No (L2) |
| `/rt/lowstate` | MEDIO | Estado articular RT | estado SDK | No (L2) |
| `/rt/odommodestate` | MEDIO | OdometrÃ­a SDK RT | estado SDK | No (L2) |
| `/rt/secondary_imu` | MEDIO | IMU interna SDK | estado SDK | No (L2) |
| `/wirelesscontroller` | MEDIO | Control remoto | estado | No |
| `/rt/wirelesscontroller` | MEDIO | Control remoto RT | estado | No |
| `/map` | BAJO | Mapa ocupaciÃ³n | nav | No (L3 solo) |
| `/map_metadata` | BAJO | Metadata mapa | nav | No (L3 solo) |
| `/cmd_vel` | AUDIT | AuditorÃ­a â€” NO publicar | seguridad | Bloquea grabaciÃ³n si publishers > 0 |
| `/api/sport/request` | AUDIT | API sport requests | SDK | No |
| `/api/sport/response` | AUDIT | API sport responses | SDK | No |

---

## Seguridad

```
REGLAS INVARIANTES:
1. NO publicar /cmd_vel en ningÃºn caso.
2. Bloquear start/timed si /cmd_vel tiene Publisher count > 0.
   Override solo con CMD_VEL_OVERRIDE=1 y justificaciÃ³n explÃ­cita.
3. NO ejecutar Nav2 durante captura.
4. Movimiento SOLO por control remoto humano fÃ­sico durante captura.
5. NO modificar bags/metadata originales (.db3, metadata.yaml).
6. NO commitear artifacts, .db3, .tar.gz, carpetas offline.
```

---

## Flujo de captura manual (prÃ³xima sesiÃ³n)

```
1. Robot encendido, en piso, control remoto listo, sensor stack activo.

2. Dry-run previo (notebook):
   ./tools/hil/ottoguide-map plan
   â†’ verificar quÃ© topics estarÃ­an disponibles
   â†’ confirmar que /cmd_vel no tiene publishers

3. PreparaciÃ³n:
   ./tools/hil/ottoguide-map prep
   â†’ inicia sensor stack si no activo
   â†’ muestra topic status

4. Inicio grabaciÃ³n:
   ./tools/hil/ottoguide-map start --label "recorrido_pasillo_norte_01"
   â†’ escribe manifiestos en SESSION/logs/
   â†’ inicia ros2 bag record con topics dinÃ¡micos

5. Recorrido humano con control remoto.
   â†’ el agente NO hace nada durante esta fase.

6. Estado intermedio (opcional):
   ./tools/hil/ottoguide-map status

7. Stop:
   ./tools/hil/ottoguide-map stop
   â†’ SIGINT al bag, espera cierre limpio

8. FinalizaciÃ³n:
   ./tools/hil/ottoguide-map finalize
   â†’ genera manifiestos, SHA256, README

9. AnÃ¡lisis offline inmediato (en notebook Windows):
   python "codigo ottoguide/tools/hil/analyze_capture_sqlite.py" \
     --bag-dir <SESSION/rosbags/bag_dir> \
     --out <SESSION/analysis>
   â†’ sqlite_analysis.json
   â†’ capture_topic_matrix.csv
   â†’ capture_analysis.md

10. Copia offline:
    ./tools/hil/ottoguide-map package
    â†’ tar.gz + sha256 en /tmp/
    â†’ scp a Windows (manual)
```

---

## Herramientas

| Herramienta | Ruta | PropÃ³sito |
|------------|------|-----------|
| `ottoguide-map` | `codigo ottoguide/tools/hil/ottoguide-map` | Captura HIL completa |
| `analyze_capture_sqlite.py` | `codigo ottoguide/tools/hil/analyze_capture_sqlite.py` | AnÃ¡lisis offline SQLite |
| `nav2_offline_smoke_test.sh` | `codigo ottoguide/tools/hil/nav2_offline_smoke_test.sh` | Test Nav2 offline |
| `detect_nav2.sh` | `codigo ottoguide/tools/hil/detect_nav2.sh` | DetecciÃ³n Nav2 runtime |

---

## Estado actual de la evidencia offline

| Captura | RUN_ID | DuraciÃ³n | DB3 | Resultado anÃ¡lisis |
|---------|--------|----------|-----|--------------------|
| Stationary 180s | 20260619_051530 | 180.02 s | 2.099 GB | L1 ready, L2/L3 NOT ready |

**ConclusiÃ³n stationary:** Ãºtil para validar estabilidad sensor. Confirma /utlidar/cloud + /livox/imu + /scan. No contiene SDK state, odom, TF ni map. Insuficiente para replay progresivo L2/L3.

**PrÃ³ximo paso:** captura de recorrido humano con control remoto, con todos los topics candidatos Unitree G1 DDS disponibles en runtime.
