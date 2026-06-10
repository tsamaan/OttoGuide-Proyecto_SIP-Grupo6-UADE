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
- **Waypoints template**: `config/navigation/waypoints_ottoguide_template.yaml`
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
