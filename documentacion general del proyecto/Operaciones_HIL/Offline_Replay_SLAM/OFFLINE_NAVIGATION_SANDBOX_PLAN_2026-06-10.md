# Offline Navigation Sandbox Plan

**Fecha**: 2026-06-10

## Objetivo del Sandbox
El objetivo de este sandbox offline es preparar el entorno de simulación, la configuración de Nav2, y la planificación de waypoints de forma virtual usando los mapas estáticos exportados, validando conceptualmente las configuraciones antes de ejecutar en el hardware físico de OttoGuide.

---

## 1. Estado actual
- Se cuenta con un **rosbag HIL estacionario validado**.
- **RViz local validado**. Los tópicos esenciales están visibles (`/map`, `/scan`, `/utlidar/cloud`).
- Se dispone de una nube acumulada diagnóstica validada y un mapa 2D (PGM/YAML) exportado localmente.
- **Limitaciones**: No hay locomoción, no se ha publicado `/cmd_vel`, y la calibración TF para el LiDAR invertido aún no está ajustada físicamente en movimiento.

## 2. Activos disponibles
- **Mapa 2D exportado**: `artifacts/maps/ottoguide_hil_stationary_map.yaml` y `.pgm`
- **Waypoints template**: `codigo ottoguide/config/navigation/waypoints_ottoguide_template.yaml`
- Grabaciones diagnósticas (MP4) de la sesión de captura.
- Scripts de análisis QA de mapas y de previsualización de waypoints.

## 3. Pruebas offline posibles
- **Tuning de costmaps**: Configurar el Global y Local Costmap de Nav2 sobre el mapa estacionario.
- **Validación de Waypoints**: Analizar y ajustar el formato JSON/YAML de los waypoints, así como la estructura del Behavior Tree (BT).
- **Simulación Fake**: Ejecutar Nav2 con un fake robot o publicando `amcl_pose` manualmente y utilizando `dummy` transform publishers para visualizar trayectorias generadas por el global planner (sin ejecutar control real).
- **QA de Mapas**: Evaluación estática de las métricas de los mapas generados.

## 4. Pruebas imposibles sin robot
- **Navegación Autónoma Real**: Ejecutar trayectorias físicas reaccionando a obstáculos dinámicos.
- **Tuning de Controladores (Local Planner)**: Ajuste fino de aceleraciones, velocidades máximas (DWA/TEB) y tolerancia a meta.
- **Validación Final TF**: Comprobación dinámica de rotaciones de odom, base_link y transformadas del LiDAR (ej. inversión de ejes en movimiento).
- **Odometría Real**: Reacción a deslizamientos o inercias físicas del robot.

## 5. Plan de navegación conceptual
El enfoque para la navegación autónoma consta de:
1. Definir los puntos clave de interés en la UADE (Recepción, Molinetes, Oficina de Alumnos, Cierre Tour) con posiciones pendientes (`null`).
2. Configurar Nav2 Offline utilizando los plugins básicos: Static Layer, Inflation Layer, y Obstacle Layer (usando el bag para simular scan).
3. Utilizar RViz2 y el panel de `Nav2 Goal` para trazar planes globales sobre el mapa PGM estático, verificando que el planner genere rutas libres de obstáculos simulados.

## 6. Checklist para siguiente sesión física
- [ ] Verificar conexión remota fluida (sin SSH si se prohíbe, vía ROS_DOMAIN_ID o VPN).
- [ ] Mapear el entorno en movimiento controlando teleop manual, obteniendo un mapa denso y navegable.
- [ ] Confirmar la posición de montaje física del LiDAR (verificar inversión de 180 grados en TF y scan).
- [ ] Ejecutar slam_toolbox de forma síncrona/asíncrona y exportar un mapa completo.
- [ ] Grabar nuevo rosbag completo que incluya tf, odom, scan y cmd_vel durante el mapeo.
- [ ] Medir las coordenadas X, Y, Yaw reales de los waypoints (Recepción, Molinetes, Oficina de Alumnos).

## 7. Criterios mínimos antes de /cmd_vel
Antes de enviar el primer comando de velocidad automático (`/cmd_vel`) al hardware, deben cumplirse **estrictamente** los siguientes criterios:
1. **Calibración TF Correcta**: La proyección del `/scan` debe coincidir perfectamente con los obstáculos físicos reportados en el mapa (el LiDAR invertido no debe causar reflexiones erróneas).
2. **Mapa Navegable Completo**: El mapa no debe ser estacionario; debe cubrir al menos la ruta de prueba completa y estar libre de ruido en las paredes.
3. **Emergency Stop**: Sistema de parada de emergencia (físico o remoto inmediato) testeado y validado.
4. **Odometría Confiable**: Rotaciones de 360° en su propio eje no deben generar drifts inaceptables en `/odom`.
5. **Aprobación Explícita**: Permiso manual para ejecutar control autónomo en un entorno despejado de personas.

---
**Nota de Riesgos:** Intentar navegación con el mapa actual puede resultar en trayectorias espurias hacia lo "desconocido" y colisiones debido a que no hay contexto del entorno.

---

## 8. Actualización 2026-06-20 — Baseline estático del sandbox

Se completó una fase de auditoría y preparación estática (sin levantar el stack Nav2 completo, sin nodos ROS, sin robot) sobre el sandbox offline ya existente (`codigo ottoguide/launch/offline_nav_sandbox.launch.py` y `codigo ottoguide/config/navigation/nav2_offline_sandbox_params.yaml`). Resultados:

- **Matriz de paquetes ROS locales**: documentada en [OFFLINE_NAVIGATION_LOCAL_CAPABILITIES.md](OFFLINE_NAVIGATION_LOCAL_CAPABILITIES.md), verificada en WSL `Ubuntu-24.04` con ROS 2 `jazzy`. Todos los paquetes Nav2 base, `tf2_ros`, `robot_state_publisher` y `rviz2` están disponibles. El paquete `nav2_loopback_sim` (usado por los launch de loopback simulation de `nav2_bringup`) **no** está instalado localmente.
- **Mapa sintético versionado**: se creó `codigo ottoguide/tests/fixtures/offline_navigation/offline_sandbox_test_map.pgm` y `.yaml`, con paredes, pasillo y un obstáculo, marcado explícitamente como `SYNTHETIC_TEST_MAP`, `NOT_UADE_MAP`, `NOT_METRICALLY_VALIDATED` y `NOT_FOR_PHYSICAL_NAVIGATION`. El default de `map_yaml` en el launch ahora apunta a este mapa versionado en lugar de `artifacts/maps/ottoguide_hil_stationary_map.yaml`.
- **Verificador de aislamiento estático**: `codigo ottoguide/tools/hil/offline_navigation/verify_sandbox_isolation.py`, que inspecciona archivos locales (sin red, sin grafo ROS) y produce un veredicto JSON `PASS`/`FAIL`.
- **Tests puros**: `codigo ottoguide/tests/unit/test_offline_navigation_sandbox_isolation.py`, ejecutables sin ROS.
- **No se completó en esta fase**: levantar el stack Nav2 completo, ejecutar nodos, publicar tópicos, ni validar L2 (odometría) o L3 (localización/mapa), que permanecen `NOT_READY` (ver [PROGRESO_ODOMETRIA_OFFLINE.md](PROGRESO_ODOMETRIA_OFFLINE.md)). El detalle de readiness por capa está en [OFFLINE_NAVIGATION_SANDBOX_READINESS.md](OFFLINE_NAVIGATION_SANDBOX_READINESS.md).

---

## 9. Actualización 2026-06-20 — Fase 2A: base de runtime ROS aislada

Se levantó por primera vez runtime ROS real (no solo archivos estáticos) para el sandbox offline, bajo aislamiento explícito y sin robot. Resultados:

- **Namespace real**: nuevo argumento de launch `sandbox_namespace` (default `offline_nav`), aplicado como namespace real (`namespace=` de `Node`) a `map_server`, `lifecycle_manager`, los `static_transform_publisher` y el simulador. Los tópicos resultantes son `/offline_nav/map`, `/offline_nav/odom` y `/offline_nav/scan`.
- **Simulador sintético**: `codigo ottoguide/tools/hil/offline_navigation/offline_runtime_simulator.py`, nodo `rclpy` exclusivo del sandbox que publica `nav_msgs/Odometry` (pose fija, velocidad cero, covarianzas conservadoras) en `odom`, TF dinámico `odom`→`base_link`, y un `sensor_msgs/LaserScan` sintético determinista en `scan`. No se ubicó en `src/navigation/` para no violar la restricción de `ROS2_INTEGRATION.md` de que `rclpy` solo se usa en `nav2_bridge.py` dentro del código de aplicación.
- **TF completo**: TF estático `map`→`odom` y `base_link`→`utlidar_lidar` (identidades sintéticas, explícitamente no extrínsecos físicos validados) agregados al launch junto con el TF dinámico del simulador.
- **Wrapper de aislamiento**: `codigo ottoguide/scripts/run_offline_navigation_runtime.sh`, que exige ejecución en WSL, exporta `ROS_LOCALHOST_ONLY=1`, exige/asigna `ROS_DOMAIN_ID` dedicado (default `77`, nunca `0`), corre el verificador en modo runtime antes de iniciar ROS, y propaga el exit code real con limpieza de procesos hijos ante `SIGINT`/`SIGTERM`.
- **Verificador en modo runtime**: `verify_sandbox_isolation.py --runtime` agregado; en este modo, `ROS_LOCALHOST_ONLY != 1` y `ROS_DOMAIN_ID` ausente o `0` pasan de warning a error, y se valida que el namespace sea real (no solo la palabra "offline" en texto).
- **Smoke test ROS real**: `codigo ottoguide/tools/hil/offline_navigation/smoke_test_offline_runtime.py`, ejecutado contra el runtime real en WSL con resultado `PASS`: recibió mensajes en `/offline_nav/map`, `/offline_nav/odom` y `/offline_nav/scan`, confirmó `/tf` y `/tf_static`, confirmó ausencia de `/cmd_vel`/`/cmd_vel_nav` globales y de nodos de hardware, y cerró sin procesos huérfanos.
- **Runbook**: [OFFLINE_NAVIGATION_SANDBOX_RUNTIME_RUNBOOK.md](OFFLINE_NAVIGATION_SANDBOX_RUNTIME_RUNBOOK.md).
- **No se completó en esta fase**: `planner_server`, `controller_server`, `behavior_server`, `waypoint_follower`, `collision_monitor`, Simple Commander, ni ninguna forma de planificación de misiones. `ROS_RUNTIME_SANDBOX` pasa de `NOT_READY` a `PARTIAL`; L2 (odometría), L3 (localización/mapa) y navegación física permanecen `NOT_READY` sin cambios — la odometría y las TF de esta fase son explícitamente sintéticas y no constituyen evidencia de L2/L3.
