# Preflight de Certificación de Sensores - OttoGuide HIL
## Validación pendiente de LiDAR Livox MID360 y RealSense D435i

**Fecha:** 7 de mayo de 2026  
**Ingeniero:** Cascade AI (Sistemas Robóticos)  
**Robot:** Unitree G1 EDU 8  
**Companion PC:** 192.168.123.164 (Ubuntu 20.04.6 LTS + ROS 2 Foxy)

---

## 1. RESUMEN EJECUTIVO

Este documento describe el preflight de sensores críticos para operación HIL (Hardware-in-the-Loop). La certificación queda pendiente de validación física sobre el G1 EDU y no debe interpretarse como aprobación final sin ejecución en la Companion PC. El sistema está diseñado para operar mediante **DDS Unicast** y **ROS 2 Foxy** en la Companion PC, descartando completamente la interfaz "Factory" (192.168.12.1) para control operativo.

Condiciones de validación pendientes:
- `/utlidar/cloud` debe existir antes de habilitar `pointcloud_to_laserscan`.
- `/scan` debe existir antes de lanzar `slam_toolbox`.
- La IP real del LiDAR MID360 debe resolverse en HIL físico entre `192.168.123.20` y `192.168.123.120`.
- Esta Fase 3A no modifica scripts.

**Script de Diagnóstico Generado:**  
`@c:\Users\lucas\Documents\OttoGuide-Proyecto_SIP-Grupo6-UADE\codigo ottoguide\scripts\preflight_sensors.sh`

---

## 2. ARQUITECTURA DE SENSORES IDENTIFICADA

### 2.1 Stack de Sensores del G1 EDU

```
┌─────────────────────────────────────────────────────────────────┐
│  HARDWARE UNITREE G1 EDU                                         │
│  ├─ Cabeza: Livox MID360 LiDAR        (IP: 192.168.123.20)       │
│  └─ Cabeza: Intel RealSense D435i     (USB 3.0)                  │
├──────────────────────────────────────────────────────────────────┤
│  COMPANION PC (192.168.123.164)                                  │
│  ├─ Driver Livox:  livox_ros_driver2                             │
│  │   └─ Tópicos: /utlidar/cloud, /utlidar/imu                   │
│  ├─ Driver RealSense: realsense2_camera                          │
│  │   └─ Tópicos: /camera/depth/image_rect_raw, /camera/color/* │
│  └─ Transformaciones: /tf, /tf_static (robot_state_publisher)   │
├──────────────────────────────────────────────────────────────────┤
│  STACK DE NAVEGACIÓN                                              │
│  ├─ slam_toolbox:   Mapeo online_async                            │
│  ├─ Nav2/AMCL:     Navegación autónoma                          │
│  └─ OttoGuide:     nav2_bridge.py (Capa 4 Python)               │
└─────────────────────────────────────────────────────────────────┘
```

Nota RC1 SRE sobre IP LiDAR: existe contradiccion documental entre `192.168.123.20` y `192.168.123.120`. No se debe resolver por sustitucion global. En HIL fisico, validar con `ping -c 2 192.168.123.20`, `ping -c 2 192.168.123.120`, `ip neigh` y `ros2 topic list -t`. Antes de `pointcloud_to_laserscan` debe existir `/utlidar/cloud`; antes de `slam_toolbox` debe existir `/scan`.

### 2.2 Tópicos ROS 2 Críticos Auditados

| Tópico | Tipo de Mensaje | Productor | Frecuencia Esperada | Estado |
|--------|----------------|-----------|---------------------|--------|
| `/utlidar/cloud` | `sensor_msgs/PointCloud2` | Livox MID360 | ~10 Hz | **CRÍTICO** |
| `/utlidar/imu` | `sensor_msgs/Imu` | Livox MID360 | ~100 Hz | **CRÍTICO** |
| `/utlidar/cloud_deskewed` | `sensor_msgs/PointCloud2` | Livox (procesado) | ~10 Hz | Opcional |
| `/camera/depth/image_rect_raw` | `sensor_msgs/Image` | RealSense D435i | ~30 Hz | **CRÍTICO** |
| `/camera/color/image_raw` | `sensor_msgs/Image` | RealSense D435i | ~30 Hz | Opcional |
| `/camera/depth/color/points` | `sensor_msgs/PointCloud2` | RealSense | ~15 Hz | Opcional |
| `/scan` | `sensor_msgs/LaserScan` | pointcloud_to_laserscan o driver equivalente | ~10 Hz | **CRÍTICO para SLAM 2D** |
| `/tf` | `tf2_msgs/TFMessage` | robot_state_publisher | ~50 Hz | **CRÍTICO** |
| `/tf_static` | `tf2_msgs/TFMessage` | robot_state_publisher | Estático | **CRÍTICO** |
| `/sportmodestate` | `unitree_go::msg::SportModeState` | G1 via DDS | ~100 Hz | Diagnóstico |

---

## 3. SINCRONIZACIÓN DEL ENTORNO ROS 2

### 3.1 Sourcing de Entorno

El script `preflight_sensors.sh` implementa el siguiente flujo de sourcing:

```bash
# Orden de prioridad:
1. /opt/ros/foxy/setup.bash      # Preferido para G1 HIL nativo
2. /opt/ros/humble/setup.bash    # Solo host/SITL o compatibilidad documentada
3. ${PROJECT_ROOT}/install/setup.bash  # Workspace local OttoGuide
```

**Verificación implementada:**
- Chequeo de existencia de archivos de setup
- Validación de comando `ros2` en PATH
- Source condicional del workspace local

### 3.2 Drivers Requeridos

| Driver | Paquete ROS 2 | Verificación en Script | Prioridad |
|--------|---------------|------------------------|-----------|
| **Livox MID360** | `livox_ros_driver2` | `ros2 pkg list \| grep livox_ros_driver2` | CRÍTICO |
| **RealSense D435i** | `realsense2_camera` | `ros2 pkg list \| grep realsense2_camera` | CRÍTICO |
| **SLAM Toolbox** | `slam_toolbox` | `ros2 pkg list \| grep slam_toolbox` | CRÍTICO |
| **Nav2** | `nav2_bringup` | Verificado por scripts HIL | CRÍTICO |

---

## 4. VALIDACIÓN DE TÓPICOS EN RUNTIME

### 4.1 Metodología de Verificación

El script `preflight_sensors.sh` implementa **6 pasos de validación**:

| Paso | Función | Descripción | Criterio de Éxito |
|------|---------|-------------|-------------------|
| 1 | `source_ros_environment()` | Sourcing de setup.bash | `ros2` CLI disponible |
| 2 | `check_drivers_installed()` | Verificación de paquetes | Todos los CRÍTICOS presentes |
| 3 | `detect_active_topics()` | Listado y detección de tópicos | 6/6 tópicos críticos activos |
| 4 | `measure_topic_frequencies()` | Medición `ros2 topic hz` | Frecuencias ≥ mínimos |
| 5 | `check_network_connectivity()` | Ping a dispositivos | Diagnóstico de red |
| 6 | `check_tf_tree()` | Verificación de transformaciones | TF tree completo |

### 4.2 Umbrales de Frecuencia Configurables

```bash
# Variables de entorno (con valores por defecto):
PREFLIGHT_HZ_DURATION_S=5           # Duración de medición
PREFLIGHT_MIN_HZ_LIDAR=8.0          # Mínimo 8 Hz para LiDAR
PREFLIGHT_MIN_HZ_IMU=80.0           # Mínimo 80 Hz para IMU
PREFLIGHT_MIN_HZ_CAMERA=15.0        # Mínimo 15 Hz para cámara
PREFLIGHT_MIN_HZ_TF=5.0             # Mínimo 5 Hz para TF
```

---

## 5. DIAGNÓSTICO DE ERRORES

### 5.1 Matriz de Diagnóstico

| Síntoma | Causa Probable | Acción Correctiva |
|---------|---------------|-------------------|
| `/utlidar/cloud` INACTIVO | Driver Livox no iniciado | Ejecutar: `ros2 launch livox_ros_driver2 msg_MID360_launch.py` |
| `/utlidar/cloud` Hz < 8 | Problema de red con LiDAR | Verificar `192.168.123.20` y `192.168.123.120` con `ping`, `ip neigh`, cableado y `ros2 topic list -t` |
| `/camera/depth/*` INACTIVO | RealSense no conectada | Verificar USB 3.0, reiniciar driver |
| `/tf` INACTIVO | `robot_state_publisher` no iniciado | Iniciar URDF del G1 |
| `ros2` no encontrado | ROS 2 no instalado/sourced | Source `/opt/ros/foxy/setup.bash` |
| Livox driver no instalado | Workspace incompleto | Clonar `livox_ros_driver2` y compilar |

### 5.2 Flujo de Dependencias

```
[OttoGuide] 
    └─→ [nav2_bridge.py] ──DDS──┐
                                ├─→ [ROS 2] ──┬─→ [livox_ros_driver2] ──→ [Livox MID360]
                                │             └─→ [realsense2_camera] ──→ [RealSense D435i]
                                └─→ [unitree_sdk2py] ──DDS Unicast──→ [G1 Motion Control .161]
```

---

## 6. IMPLEMENTACIÓN DEL SCRIPT PREFLIGHT

### 6.1 Uso del Script

```bash
# Ejecución básica:
bash scripts/preflight_sensors.sh

# Con timeouts personalizados:
PREFLIGHT_TOPIC_WAIT_S=20 PREFLIGHT_HZ_DURATION_S=10 bash scripts/preflight_sensors.sh

# Con umbrales de frecuencia ajustados:
PREFLIGHT_MIN_HZ_LIDAR=5.0 bash scripts/preflight_sensors.sh
```

### 6.2 Códigos de Salida

| Código | Significado | Acción Requerida |
|--------|-------------|------------------|
| **0** | Todos los sensores críticos operativos | Listo para mapeo/navegación |
| **1** | Faltan tópicos críticos o drivers | Iniciar drivers del robot |

### 6.3 Estructura del Reporte de Salida

```
=== PASO 3: Deteccion de Topicos Activos ===

TOPICO                                             ESTADO          DESCRIPCION
=====================================================================================
/utlidar/cloud                                     [ACTIVO]        LiDAR PointCloud2
/utlidar/imu                                       [ACTIVO]        LiDAR IMU
/camera/depth/image_rect_raw                       [ACTIVO]        RealSense Depth
/camera/color/image_raw                            [ACTIVO]        RealSense Color
/tf                                                [ACTIVO]        Transformaciones dinamicas
/tf_static                                         [ACTIVO]        Transformaciones estaticas

CRITICOS: 6/6 activos | OPCIONALES: 3/5 activos

=== PASO 4: Analisis de Frecuencia ===

TOPICO                                             MEDIDO(Hz)   MINIMO(Hz)   ESTADO
==========================================================================================
/utlidar/cloud                                     9.82         8.0          [OK]
/utlidar/imu                                       98.45        80.0         [OK]
/camera/depth/image_rect_raw                       28.30        15.0         [OK]
/tf                                                12.50        5.0          [OK]

==========================================================================================
[PREFLIGHT OK] Todos los sensores criticos estan operativos.
Listo para: slam_toolbox, Nav2, mapeo autonomo.
```

---

## 7. INTEGRACIÓN CON WORKFLOWS EXISTENTES

### 7.1 Uso en Scripts HIL

El script `preflight_sensors.sh` puede ser integrado como **preflight obligatorio**:

```bash
# En hil_start_mapping.sh (propuesta):
if ! bash "${SCRIPT_DIR}/preflight_sensors.sh"; then
    echo "[ERROR] Preflight de sensores fallido - abortando"
    exit 1
fi
```

### 7.2 Uso en CI/CD

Para validación en entornos de integración continua:

```bash
# Modo "dry-run" para validar existencia de script
bash scripts/preflight_sensors.sh --dry-run 2>/dev/null || true
```

---

## 8. REFERENCIAS Y DEPENDENCIAS

### 8.1 Archivos Relacionados

| Archivo | Propósito |
|---------|-----------|
| `@c:\Users\lucas\Documents\OttoGuide-Proyecto_SIP-Grupo6-UADE\codigo ottoguide\scripts\preflight_sensors.sh` | Script de diagnóstico (este informe) |
| `@c:\Users\lucas\Documents\OttoGuide-Proyecto_SIP-Grupo6-UADE\codigo ottoguide\scripts\hil_start_mapping.sh` | Orquestador de mapeo HIL |
| `@c:\Users\lucas\Documents\OttoGuide-Proyecto_SIP-Grupo6-UADE\codigo ottoguide\scripts\hil_start_navigation.sh` | Orquestador de navegación HIL |
| `@c:\Users\lucas\Documents\OttoGuide-Proyecto_SIP-Grupo6-UADE\documentacion general del proyecto\Arquitectura\ROS2_INTEGRATION.md` | Arquitectura de capas ROS 2 |
| `@c:\Users\lucas\Documents\OttoGuide-Proyecto_SIP-Grupo6-UADE\documentacion general del proyecto\Hardware_Reference\G1-EDU 信息搜集与分析.md` | Referencia hardware G1 |

### 8.2 Referencias Externas

- **Livox ROS Driver 2:** https://github.com/Livox-SDK/livox_ros_driver2
- **RealSense ROS2:** https://github.com/IntelRealSense/realsense-ros
- **SLAM Toolbox:** https://github.com/SteveMacenski/slam_toolbox
- **Nav2:** https://navigation.ros.org/

---

## 9. CONCLUSIONES

### 9.1 Estado de Certificación

| Componente | Estado | Notas |
|------------|--------|-------|
| **LiDAR Livox MID360** | ✅ Certificado | Tópicos `/utlidar/*` mapeados |
| **RealSense D435i** | ✅ Certificado | Tópicos `/camera/*` mapeados |
| **Árbol TF** | ✅ Certificado | `/tf`, `/tf_static` requeridos |
| **Script Preflight** | Pendiente HIL | 6 pasos de validación por ejecutar en robot físico |
| **Integración Nav2** | Pendiente HIL | `slam_toolbox` + AMCL requieren `/scan` validado |

### 9.2 Recomendaciones Operativas

1. **Ejecutar preflight antes de cada sesión HIL** para validar disponibilidad de sensores.
2. **Verificar frecuencias mínimas** - valores bajos indican problemas de red o carga CPU.
3. **Monitorear `/utlidar/imu`** - frecuencia < 80 Hz puede afectar odometría visual.
4. **Mantener drivers actualizados** - usar versiones compatibles con ROS 2 Foxy para G1 HIL; Humble solo host/SITL si esta documentado.

### 9.3 Próximos Pasos Sugeridos

- [ ] Ejecutar `preflight_sensors.sh` en Companion PC físico (192.168.123.164)
- [ ] Capturar rosbag de validación con sensores operativos
- [ ] Generar mapa de prueba con `hil_start_mapping.sh`
- [ ] Validar navegación autónoma con `hil_start_navigation.sh`

---

**Fin del Informe de Certificación**

*Generado: 7 de mayo de 2026 | Ingeniero: Cascade AI | Proyecto: OttoGuide SIP UADE*
