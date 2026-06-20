# Progreso de Odometría Offline — OttoGuide

**Estado:** EN INVESTIGACIÓN  
**Fecha inicial:** 2026-06-20

## 1. Objetivo y alcance

Este documento registra la evidencia offline para convertir capturas LiDAR del Unitree G1 EDU 8 con Livox MID360 en una trayectoria confiable. El alcance actual termina en la evaluación de scan matching y observabilidad de estacionariedad; no incluye publicar odometría, TF, SLAM, mapas ni Nav2.

## 2. Restricciones de seguridad

El trabajo se realiza sin conexión al robot y sin red durante el análisis. No se reproducen bags, no se publican topics ROS y no se modifican los tar, DB3 ni resultados previos. Joystick e IMU no se usan como entradas del modelo; el joystick se limita a producir etiquetas temporales para evaluación offline.

## 3. Entorno y datasets

Entorno confirmado: Windows 11, WSL `Ubuntu-24.04`, ROS 2 Jazzy, Python 3.12.3, SciPy 1.11.4 y Matplotlib 3.6.3.

| Captura | Duración | Mensajes | Actividad de joystick | Uso experimental |
|---|---:|---:|---:|---|
| A, `20260620_055435` | 179.937 s | 585586 | ~41.7 % | Recorrido intermitente por pasillo entre escritorios; `TRANSLATION_AND_CORRIDOR_DOMINANT` |
| B, `20260620_060729` | 600.059 s | 1967649 | ~3.2 % | Movimiento localizado, circular y sobre sí mismo, con neutralidad prolongada; `LOCALIZED_ROTATION_AND_STATIONARY_DOMINANT` |

Ambas capturas pasaron integridad, consistencia metadata/SQLite y completitud de 9/9 topics. No contienen `/odom`, `/tf`, `/tf_static`, `/map`, `/cmd_vel` ni topics de control.

Las capturas se hicieron en el mismo entorno general de oficinas, pero comenzaron en puntos físicos distintos, tienen orígenes locales independientes y no comparten una orientación inicial confirmada. No son repeticiones del mismo recorrido: A cubre un trayecto espacial más amplio y predominantemente traslacional, mientras B concentra poca traslación, giros y largos períodos neutrales. Sin una referencia externa no pueden alinearse directamente ni compararse sus coordenadas absolutas, poses finales o longitudes de recorrido como error entre repeticiones.

## 4. Pipeline de captura

El pipeline disponible es: captura física cruda, validación de integridad, inspección deserializada, agregación temporal de `/scan`, scan matching 2D y evaluación offline. La progresión posterior prevista es trayectoria confiable, odometría validada, TF, SLAM, mapa 2D, localización y sandbox Nav2; esas etapas posteriores permanecen bloqueadas.

## 5. Hallazgos sobre los mensajes

- `PointCloud2` contiene 96 puntos por mensaje, 100 % finitos y sin timestamp por punto; esto bloquea el deskew requerido por LIO directo.
- Cada `LaserScan` tiene 723 rayos y baja cobertura finita individual (~4.98 %), pero la agregación alcanza ~94.2 % a 100 ms y ~95.1 % a 250 ms.
- Cloud y scan agregados a 250 ms coinciden en 98.3 % de bins dentro de 0.10 m.
- La IMU Livox entrega datos monotónicos a 200 Hz, sin orientación disponible; no se utiliza como predictor en esta fase.

## 6. Cronología experimental

| Fase | Entrada | Método | Resultado | Decisión | Artefacto local |
|---|---|---|---|---|---|
| Dual capture triage | Capturas A y B | Integridad y continuidad | Triage completo; B favorecida por continuidad | Ambas aptas para análisis | `artifacts/offline_processing/20260620_dual_capture_triage` |
| Deserialized sampling | Topics de ambas capturas | Muestreo de mensajes | Scan agregado viable; LIO directo bloqueado | Usar scan matching agregado | `artifacts/offline_processing/20260620_deserialized_sampling` |
| Point-to-point ICP | `/scan` agregado | ICP frame-to-frame, 100/250 ms | 100 ms condicional; 250 ms suprime movimiento | Descartar 250 ms | `artifacts/offline_processing/20260620_aggregated_scan_icp` |
| Point-to-line ICP | `/scan` agregado 100 ms | ICP frame-to-frame con normales | Reduce drift 27.2 % en A y 47.8 % en B | Baseline `POINT_TO_LINE_CONDITIONAL` | `artifacts/offline_processing/20260620_point_to_line_icp` |
| Scan-to-submap | Baseline point-to-line | Submap local | Baja aceptación en A y drift mayor | `SCAN_TO_SUBMAP_REJECTED` | `artifacts/offline_processing/20260620_scan_to_submap` |
| Quality-gated scan-to-submap | Submap y gate congelado | Gate de calidad de keyframes | 0 keyframes insertados; gate incompatible | `QUALITY_GATED_SUBMAP_REJECTED` | `artifacts/offline_processing/20260620_quality_gated_submap` |
| Stationarity observability | Métricas point-to-line | Features causales y regresión logística cross-capture | AUC alta, pero transferencia operativa asimétrica | `REGISTRATION_ONLY_STATIONARITY_NOT_OBSERVABLE` | `artifacts/offline_processing/20260620_p2l_stationarity_observability` |

## 7. Comparación de algoritmos

| Método | Capture A | Capture B | Fortaleza | Limitación | Clasificación |
|---|---|---|---|---|---|
| Point-to-point 100 ms | 99.94 % éxito; RMSE 0.027 m; drift 0.075–0.094 m/s | No consolidado | Alta disponibilidad | Drift neutral elevado | `CONDITIONAL` |
| Point-to-point 250 ms | 100 % éxito; RMSE 0.0095 m; recorrido 2.4 m | No consolidado | RMSE y drift aparentes bajos | Solapamiento suprime movimiento real | `DESCARTADO` |
| Point-to-line 100 ms | 97.05 % éxito; drift 0.058–0.064 m/s | 96.6 % éxito activo; drift 0.038–0.057 m/s | Mejor reducción consistente de drift | No supera el umbral en 5/6 ventanas; más rechazos | `POINT_TO_LINE_CONDITIONAL` |
| Scan-to-submap | 6.6 % éxito activo; drift 0.140–0.237 m/s | 85.5 % éxito activo; drift 0.154–0.240 m/s | Prueba acumulación local | 0/6 ventanas bajo 0.05 m/s | `SCAN_TO_SUBMAP_REJECTED` |
| Quality-gated scan-to-submap | 0/1303 keyframes; drift 0.150–0.272 m/s | 0/1632 keyframes; drift 0.154–0.191 m/s | Gate sintético 11/11 PASS | Bloquea todo crecimiento y no prueba selectivamente la hipótesis | `QUALITY_GATED_SUBMAP_REJECTED` |

## 8. Decisiones técnicas

El baseline vigente es point-to-line frame-to-frame a 100 ms. La decisión actual es `RETURN_TO_FRAME_TO_FRAME_WITH_STATIONARITY_NOISE_MODEL`. La hipótesis `SUBMAP_SELF_REINFORCEMENT` permanece inconclusa: el gate aplicado no permitió comparar keyframes buenos contra malos.

El análisis de observabilidad construyó 1797 filas para A y 1819 para B, sin joystick ni IMU como predictores. Model C obtuvo AUC 0.8803 en A→B y 0.8936 en B→A, pero no cumplió los criterios operativos en ambos folds: A→B tuvo balanced accuracy 0.7135 y especificidad 0.4382; B→A tuvo balanced accuracy 0.7527 y recall activo 0.5598. Por los umbrales congelados se clasifica `REGISTRATION_ONLY_STATIONARITY_NOT_OBSERVABLE` y se decide `REQUIRE_NEW_DATA_OR_GROUND_TRUTH`.

Los folds A→B y B→A se reinterpretan como `CROSS_DOMAIN_MOTION_TRANSFER_TEST`, no como `SAME_ROUTE_CROSS_VALIDATION`. La asimetría puede estar afectada por el régimen traslacional de A frente al régimen neutral/rotacional de B, el desbalance de clases, la geometría observada, las distribuciones de velocidad y maniobras, y las distintas duraciones. Las features contienen señal discriminante, pero no produjeron una decisión binaria transferible entre estos dos dominios. Con estas capturas no puede aislarse si el fallo corresponde al algoritmo, al threshold, al cambio de dominio o a las etiquetas indirectas: el joystick representa intención del operador, no movimiento físico medido.

Las magnitudes y agregados temporales de movimiento muestran separación univariada consistente. Sin embargo, el control quality-only alcanzó solo AUC 0.6691/0.6482, mientras motion/coherence-only alcanzó 0.9745/0.8886. Retirar las magnitudes instantáneas `delta_translation` y `abs_delta_yaw` mantuvo AUC 0.8804/0.8930: el resultado depende de la familia de movimiento estimado por el registro, no exclusivamente de esas dos salidas instantáneas. Los labels permutados dieron AUC media 0.4780/0.4690.

## 9. Enfoques descartados

No se repetirán LIO directo con estas capturas, ICP individual, ICP a 250 ms, point-to-point como solución final, warm start con último delta ni las variantes scan-to-submap ya evaluadas. Tampoco se seguirá optimizando submaps en este incremento.

## 10. Estado actual de readiness

| Nivel | Estado | Evidencia |
|---|---|---|
| L0 sensores | READY | Capturas íntegras y topics completos |
| L1 intención/movimiento | READY | Intervalos de evaluación definidos |
| L2 odometría | NOT READY | No existe trayectoria offline confiable |
| L3 localización/mapa | NOT READY | Depende de L2 validado |

## 11. Bloqueos pendientes

Persisten drift neutral, convergencias rechazadas, ausencia de timestamp por punto para deskew y falta de una señal de estacionariedad transferible con sensibilidad y especificidad suficientes entre capturas. La principal limitación es que A y B pertenecen a dominios de movimiento y recorridos distintos; no hay validación same-route ni ground truth independiente de pose. Esto impide separar el error del algoritmo del cambio de dominio y refuerza la decisión de adquirir evidencia estandarizada.

## 12. Próximo incremento

La decisión siguiente es `REQUIRE_NEW_DATA_OR_GROUND_TRUTH`. El [Plan de Captura con Ground Truth para Odometría](PLAN_CAPTURA_GROUND_TRUTH_ODOMETRIA.md), su tooling schema `1.0` y el [runbook de preflight CALIBRATION GT-MIN](RUNBOOK_CALIBRATION_GT_MIN_PREFLIGHT.md) ya fueron preparados. El contrato separa tolerancias, sella route spec/inventario/revisión humana, exige doble sync y usa exit codes fail-safe sin autorizar movimiento; hardware real, revisión humana real y captura permanecen pendientes. El protocolo separa reproducibilidad same-route de generalización entre dominios. No se implementa un filtro ni se corrige o acumula una trayectoria nueva.

### 12.1 Origen físico y contrato de comparabilidad

Cada recorrido comparable debe tener una marca física de origen en el piso, una flecha de orientación inicial y la posición nominal del centro de referencia del robot. La tolerancia inicial provisional será de ±0.02 m en posición y ±2° en yaw. Se debe conservar una fotografía o croquis, el identificador único del recorrido y cualquier desviación observada al colocar el robot.

El frame offline de una repetición comienza en `x=0`, `y=0`, `yaw=0` solo cuando la colocación está dentro de esas tolerancias. Fuera de tolerancia debe medirse y registrar una corrección inicial respaldada por una referencia externa; si no existe esa medición, la captura se marca `NOT_COMPARABLE`.

### 12.2 Sesiones mínimas

| Sesión | Diseño | Uso y exclusiones |
|---|---|---|
| `CALIBRATION` | Origen y orientación marcados, recorrido estandarizado y distancias/ángulos medidos; mínimo 2 pasadas | Verificar frames, sincronización, herramientas y ground truth; no aporta métricas finales |
| `DEVELOPMENT` | Mismo origen y ruta estandarizada; mínimo 3 repeticiones por recorrido | Diseñar features y ajustar thresholds; no se usa como validación final |
| `VALIDATION-SAME-ROUTE` | Mismo origen, orientación, segmentos, distancias y orden de maniobras; mínimo 3 repeticiones independientes | Validación comparable final; queda congelada y no se usa para ajustar thresholds |
| `VALIDATION-DOMAIN-SHIFT` | Corredor traslacional, área reducida rotacional, secuencia combinada y neutralidad prolongada; mínimo 2 repeticiones por dominio | Evaluar generalización y estabilidad de thresholds; no comparar trayectorias diferentes entre sí |

### 12.3 Matriz de recorridos

| Recorrido | Tipo dominante | Mismo origen | Mismo trayecto | Uso | Longitud y giros esperados | Segmentos estacionarios | Repeticiones mínimas |
|---|---|---:|---:|---|---|---|---:|
| R1 | Pasillo traslacional | Sí | Sí | Reproducibilidad | Croquis y distancia total medidos; giros nominales anotados | Inicio, fin y al menos 2 paradas intermedias de 10 s | 3 development + 3 validation |
| R2 | Área reducida rotacional | Sí | Sí | Rotación y estacionariedad | Centro y ángulos acumulados marcados | Inicio, entre sentidos de giro y fin, 10 s cada uno | 3 development + 3 validation |
| R3 | Combinado | Sí | Sí | Validación integrada | Segmentos rectos y giros medidos en orden fijo | Al menos 3 paradas de 10 s | 3 development + 3 validation |
| R4 | Recorrido libre distinto | No necesariamente | No | Domain shift | Documentados por captura, sin exigir coincidencia geométrica | Al menos 2 períodos de 30 s | 2 por variante |

Cada ficha R1–R4 debe incluir identificador versionado, croquis, longitud esperada, giros esperados, orden de maniobras, segmentos estacionarios, tolerancias y cantidad efectiva de repeticiones. R1–R3 usan como tolerancias iniciales ±0.02 m y ±2°; las tolerancias de distancia y ángulo por segmento deben declararse antes de capturar según el instrumento de medición disponible.

### 12.4 Ground truth y métricas separadas

El ground truth mínimo debe provenir de marcas y mediciones físicas independientes del registro LiDAR: distancias de segmentos, posiciones de parada y ángulos nominales. Si se dispone de tracking externo sincronizado, debe conservarse su frame, precisión y transformación al origen marcado.

Para repeticiones del mismo recorrido se permiten error final de posición y yaw, ATE, RPE, path length ratio, consistencia entre repeticiones, drift por segmento y error por maniobra. ATE/RPE requieren ground truth propio o una alineación externa definida; no se usa una repetición como verdad implícita sin declarar el método.

Para recorridos diferentes solo se permiten métricas independientes por captura: drift neutral, tasa de éxito, disponibilidad, error contra ground truth propio, error por segmento, generalización de clasificadores y estabilidad de thresholds. No se calcula ATE entre A y B ni entre otros recorridos diferentes, y las métricas de validación comparable no se mezclan con las de domain shift.

## 13. Artefactos locales relacionados

Los artefactos bajo `artifacts/offline_processing/` son locales y no necesariamente están versionados en Git. Directorios relacionados:

- `20260620_dual_capture_triage`
- `20260620_deserialized_sampling`
- `20260620_aggregated_scan_icp`
- `20260620_point_to_line_icp`
- `20260620_scan_to_submap`
- `20260620_quality_gated_submap`
- `20260620_p2l_stationarity_observability`

## 14. Historial de actualizaciones

| Fecha | Fase | Cambio |
|---|---|---|
| 2026-06-20 | Consolidación inicial | Se documentaron las capturas y los experimentos offline hasta quality-gated scan-to-submap. |
| 2026-06-20 | Observabilidad de estacionariedad | Se evaluó la transferencia cross-capture de features derivadas de point-to-line frame-to-frame. |
| 2026-06-20 | Contexto físico de las capturas | Se aclaró que A y B corresponden a recorridos, orígenes y regímenes de movimiento diferentes; la evaluación cross-capture se reinterpreta como domain shift. |
| 2026-06-20 | Preparación de ground truth | Se documentó el protocolo GT-MIN/GT-CONT y se preparó tooling offline de creación y validación de sesiones; no se realizó captura física. |
| 2026-06-20 | Endurecimiento de preflight GT-MIN | Se versionó schema 1.0, se selló la especificación de ruta y se añadió evaluación read-only de readiness físico; el estado permanece NO-GO. |
| 2026-06-20 | Cierre fail-safe GT-MIN | Se añadieron exit codes inequívocos, inventario y revisión humana sellados, doble sincronización y rechazo de placeholders; no se realizó revisión ni captura física. |
