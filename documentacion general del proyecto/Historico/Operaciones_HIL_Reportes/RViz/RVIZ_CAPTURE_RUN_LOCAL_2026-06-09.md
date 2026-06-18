# Captura local RViz acumulada — OttoGuide

## Última ejecución validada

- RUN_ID: 20260610_003636
- Evidencia local: `artifacts/evidence/rviz_manual_capture_20260610_003636/`
- Video: `RvizFast.mp4`
- Tipo de video: manual, editado/acelerado
- Duración: 35.301933 s
- Tamaño: 75048611 B (~71.5 MB)
- Frame inicial: `images/rviz_accumulated_start_20260610_003636.png`
- Frame final: `images/rviz_accumulated_final_20260610_003636.png`
- Mapa PGM: `maps/ottoguide_hil_stationary_map_20260610_003636.pgm`
- Mapa YAML: `maps/ottoguide_hil_stationary_map_20260610_003636.yaml`

## Interpretación

El video muestra la acumulación visual diagnóstica de `/utlidar/cloud` en RViz sobre el mapa 2D `/map`. La acumulación se genera mediante `Decay Time` y sirve como evidencia de percepción HIL local.

## Limitaciones

- No es mapa 3D navegable.
- No es SLAM 3D completo.
- No prueba navegación autónoma.
- El bag es estacionario.
- No se ejecutó Nav2.
- No se ejecutó `/cmd_vel`.
- No hubo locomoción.

## Política de versionado

Los binarios quedan fuera de Git por peso:

- `artifacts/evidence/`
- videos `.mp4`
- mapas `.pgm` / `.yaml`
- rosbags `.db3` / `.bag` / `.mcap`

**Nota:** El método final recomendado para la captura es grabación manual (Windows/OBS/Xbox Game Bar), ya que `x11grab` en WSLg headless puede capturar pantallas negras debido a la configuración gráfica.
