# Plan de Captura con Ground Truth para Odometría — OttoGuide

**Estado:** DISEÑO OFFLINE — PENDIENTE DE VALIDACIÓN FÍSICA

## 1. Objetivo

Definir sesiones reproducibles con referencia independiente para evaluar trayectoria 2D, estacionariedad, escala, rotación, drift, error por segmento, repetibilidad y generalización entre dominios. Este plan implementa la decisión `REQUIRE_NEW_DATA_OR_GROUND_TRUTH` registrada en [PROGRESO_ODOMETRIA_OFFLINE.md](PROGRESO_ODOMETRIA_OFFLINE.md).

## 2. Evidencia y motivación

El baseline point-to-line frame-to-frame a 0.10 s es `POINT_TO_LINE_CONDITIONAL`. Las features de registro contienen señal discriminante, pero un threshold fijo no transfirió operativamente entre los dominios A y B; el joystick mide intención y no movimiento físico. Se necesita una referencia independiente y capturas comparables antes de ajustar otro threshold.

## 3. Alcance y exclusiones

Esta fase diseña documentación, formatos y validadores offline. No realiza captura física, detección visual, estimación de pose, odometría, TF, SLAM o Nav2; no reproduce bags ni modifica ICP. El RMSE interno del matcher no se acepta como métrica final por sí solo.

## 4. Relación entre las capturas existentes

A y B pertenecen al mismo entorno general, pero tienen rutas, orígenes y orientaciones iniciales diferentes. A es `TRANSLATION_AND_CORRIDOR_DOMINANT`; B es `LOCALIZED_ROTATION_AND_STATIONARY_DOMINANT`. Su evaluación es `CROSS_DOMAIN_MOTION_TRANSFER_TEST`, no `SAME_ROUTE_CROSS_VALIDATION`; no corresponde calcular ATE entre ellas. El contexto completo permanece en el documento de progreso.

## 5. GT-MIN

`GT-MIN` es `SEGMENT_LEVEL_GROUND_TRUTH`, ejecutable sin motion capture profesional. Usa origen y orientación marcados, distancias y ángulos nominales medidos, puntos de parada, eventos, tolerancia declarada del instrumento y al menos tres repeticiones por maniobra.

El contrato vigente es schema `1.0`. Cada sesión referencia una [route spec de ejemplo](../../../codigo%20ottoguide/tools/hil/ground_truth/templates/route_spec.example.json), copiada y sellada por SHA-256. El [inventario físico de ejemplo](../../../codigo%20ottoguide/tools/hil/ground_truth/templates/hardware_inventory.example.json) y la [revisión humana de ejemplo](../../../codigo%20ottoguide/tools/hil/ground_truth/templates/human_review.example.json) son conservadores y producen NO-GO. Inventario y revisión se copian a `calibration/`, se sellan por hash y se vinculan al manifest por path, ID y revisión.

| Maniobra mínima | Referencia segmentaria |
|---|---|
| Estacionario 60 s | Pose inicial/final marcada y duración medida |
| Recta 1 m, 2 m y 3 m | Marcas de inicio/fin y distancia instrumental |
| Recta en sentido inverso | Mismas marcas, dirección opuesta |
| Giro +90°, -90° y 180° | Orientaciones marcadas y tolerancia angular |
| Secuencia combinada | Orden fijo de rectas, paradas y giros |
| Retorno próximo al origen | Error final respecto de la marca física |

GT-MIN no entrega necesariamente pose continua entre eventos. Cada segmento debe declarar estado esperado, medición, tolerancia, sentido, velocidad nominal si se controla y fuente de la referencia.

## 6. GT-CONT

GT-CONT requiere pose 2D independiente continua `x`, `y`, `yaw`. El concepto preferido es una cámara externa fija calibrada contra el piso y un marcador rígido unido al robot. Debe resolver intrínsecos, homografía o extrínsecos al piso, pose marcador→robot, sincronización, oclusiones, campo visual, precisión, gaps y transformación a `gt_world`.

No se implementa visión en esta fase. Una RealSense fue observada en documentación HIL previa, pero no está confirmado que esté disponible para la sesión, pueda operar como cámara externa fija o tenga montaje/calibración apropiados. `GT_CONT_STATUS=PENDING_HARDWARE_CONFIRMATION`.

## 7. Recursos y hardware pendientes

| Recurso | Estado |
|---|---|
| Cinta o instrumento de distancia con precisión declarada | `PENDING_HARDWARE_CONFIRMATION` |
| Instrumento o plantilla para ángulos | `PENDING_HARDWARE_CONFIRMATION` |
| Marcas removibles de piso y flecha de orientación | `PENDING_HARDWARE_CONFIRMATION` |
| Cámara externa fija, soporte/trípode y campo visual suficiente | `PENDING_HARDWARE_CONFIRMATION` |
| Marcador rígido y montaje marcador→robot | `PENDING_HARDWARE_CONFIRMATION` |
| RealSense apta como referencia independiente | `PENDING_HARDWARE_CONFIRMATION` |
| Mecanismo visible/registrado de sincronización | `PENDING_HARDWARE_CONFIRMATION` |

No se presupone AprilTag, ArUco, motion capture ni ningún instrumento específico.

## 8. Sesiones experimentales

| Fase | Repeticiones | Uso |
|---|---:|---|
| `CALIBRATION` | ≥2 pasadas | Verificar frames, tiempos, referencias y tooling; excluida de métricas finales |
| `DEVELOPMENT` | ≥3 por ruta | Diseño y ajuste; nunca evidencia final |
| `VALIDATION-SAME-ROUTE` | ≥3 independientes | Misma ruta/origen/orientación/orden; validación decisiva sin reajuste |
| `VALIDATION-DOMAIN-SHIFT` | ≥2 por dominio | Corredor, rotación localizada, combinado y neutralidad; generalización solamente |

## 9. Matriz de recorridos

| ID | Dominio | Origen marcado | Trayecto repetible | Uso |
|---|---|---:|---:|---|
| R1 | Pasillo traslacional | Sí | Sí | Reproducibilidad y distancia |
| R2 | Área reducida rotacional | Sí | Sí | Yaw y estacionariedad |
| R3 | Combinado | Sí | Sí | Validación integrada |
| R4 | Recorrido libre distinto | No necesariamente | No | Domain shift |

Cada ficha debe incluir croquis versionado, posición y orientación de origen, longitud, giros, orden, paradas, tolerancias, repeticiones y criterio de comparabilidad. R1 incluye 1/2/3 m e inversa; R2 los giros ±90°/180° y 60 s estacionario; R3 la secuencia combinada y retorno; R4 varía el orden y no se compara geométricamente con otras rutas.

## 10. Origen físico y comparabilidad

Se marca en el piso el centro nominal de `gt_robot` y su eje +x. Tolerancia provisional: ±0.02 m y ±2°. Se registra fotografía o croquis, instrumento, tolerancia y desviación inicial. Solo dentro de tolerancia se inicializa `x=0`, `y=0`, `yaw=0`; de lo contrario se registra una corrección externa medida o `comparability_status=NOT_COMPARABLE`.

## 11. Frames y convenciones

- `gt_world`: frame cartesiano fijo al piso, +x en la dirección inicial marcada, +y a la izquierda, +z hacia arriba.
- `gt_robot`: centro planar nominal del robot; x hacia adelante, y a la izquierda; yaw positivo antihorario alrededor de +z.
- `lidar_sensor`: frame reportado por el LiDAR; su relación física debe medirse.
- Unidades: metros, radianes, segundos y nanosegundos.

Las transformaciones marcador→`gt_robot` y `gt_robot`→`lidar_sensor` están pendientes de medición. No se publican TF ni se presentan extrínsecos como validados.

## 12. Contrato temporal

Se conservan por separado timestamp ROS, timestamp SQLite, reloj de cámara, tiempo relativo y offset estimado. `ground_truth_events.csv` contiene:

```text
timestamp_ns,relative_time_s,event_id,event_type,segment_id,expected_state,expected_x_m,expected_y_m,expected_yaw_rad,position_tolerance_m,yaw_tolerance_rad,time_tolerance_s,source,notes
```

Las tolerancias se separan por unidad: posición en metros, yaw en radianes y tiempo en segundos. Son opcionales cuando la magnitud no aplica, finitas y no negativas cuando aparecen. Toda pose esperada y todo `SEGMENT_END` declaran las tolerancias aplicables; `SYNC_MARKER` siempre declara `time_tolerance_s`. La columna ambigua anterior fue retirada antes de existir sesiones físicas.

Debe existir un `SYNC_MARKER` inicial y otro final observables en las fuentes aplicables. El offset se estima contra el tiempo relativo de la sesión; para GT-CONT se ajusta además un modelo afín para medir drift de reloj. Tolerancias provisionales para revisión física: residuo de sincronización ≤0.050 s y drift ≤0.010 s/min. Si falta un marcador, el residuo supera 0.050 s, el drift supera 0.010 s/min o el orden temporal no puede demostrarse, la fuente queda `NOT_COMPARABLE` para métricas temporales.

## 13. Estructura de una sesión

```text
<session_id>/
  session_manifest.json
  ground_truth/ground_truth_events.csv
  raw/
  external/
  calibration/
  reports/
  notes/README.txt
```

El manifest registra fase, ruta, dominio, origen, comparabilidad, precisión, sincronización y referencias relativas. Archivos grandes permanecen fuera de Git.

La evidencia de preflight sellada añade `calibration/hardware_inventory.json` y `calibration/human_review.json`. Una modificación posterior que no coincida con el SHA-256 registrado vuelve el dataset `INVALID`; una revisión ausente, vencida, NO-GO o inconsistente mantiene estructura válida pero produce `physical_ready=false`.

## 14. Procedimiento de captura

1. Asignar fase, ruta e ID únicos; congelar ficha y tolerancias.
2. Confirmar checklist, zona, instrumento y responsables sin mover el robot.
3. Marcar origen, +x, segmentos, paradas y ángulos; medir y fotografiar el croquis.
4. Preparar el directorio con el tooling y completar manifest.
5. Colocar el robot, medir desviación y decidir comparabilidad.
6. Iniciar las referencias, emitir marcador de sincronización y registrar `SESSION_START`.
7. Ejecutar manualmente la ruta y anotar eventos; este documento no autoriza ni ejecuta movimiento.
8. Emitir marcador final y `SESSION_END`; detener fuentes.
9. Copiar referencias sin modificar originales, completar paths y validar.
10. Sellar validation; cualquier ajuste posterior invalida su uso como evaluación final.

## 15. Sincronización

El marcador inicial estima offset; el final permite estimar drift. Cada fuente conserva su reloj original y una tabla de conversión a `relative_time_s`. Los gaps GT se delimitan con `GROUND_TRUTH_GAP_START/END`. No se interpola silenciosamente una oclusión; toda interpolación futura debe conservar máscara de disponibilidad y duración.

## 16. Métricas

| Grupo | Métricas |
|---|---|
| GT continuo | ATE/RPE traslacional y angular, errores finales, escala, path length ratio |
| Estacionariedad | Drift total, m/s, rad/s, false moving y false stationary rates |
| GT segmentario | Errores de distancia, yaw y parada; repetibilidad; sesgo por dirección y velocidad |
| Disponibilidad | Porcentaje válido, gaps, frames perdidos, oclusiones y máxima duración sin referencia |

ATE/RPE solo se calculan contra GT propio en un frame demostrado. Para rutas diferentes se reportan métricas independientes, generalización de clasificadores y estabilidad de thresholds, nunca error directo entre trayectorias.

## 17. Separación development/validation

CALIBRATION verifica el sistema. DEVELOPMENT puede ajustar diseño y thresholds. Antes de VALIDATION-SAME-ROUTE se congelan código, parámetros, rutas y criterios; sus datos no regresan al ajuste. VALIDATION-DOMAIN-SHIFT produce un reporte separado y no sustituye same-route.

## 18. Criterios GO/NO-GO

GO requiere hardware confirmado, ficha de ruta aprobada, origen verificable, tolerancias instrumentales declaradas, almacenamiento disponible, relojes identificados, doble sync planificado, herramientas PASS y revisión de seguridad física vigente. Cualquier ausencia implica NO-GO. Estado actual: `NO_GO_PENDING_HARDWARE_AND_HUMAN_REVIEW`.

El procedimiento reproducible está en [RUNBOOK_CALIBRATION_GT_MIN_PREFLIGHT.md](RUNBOOK_CALIBRATION_GT_MIN_PREFLIGHT.md). `ok` valida estructura y hashes; `physical_ready` exige inventario vigente, revisión humana GO consistente, origen dentro de tolerancia, doble sync, recursos confirmados y ausencia de placeholders críticos. El assess devuelve 0 para GO, 2 para NO-GO, 3 para INVALID y 1 para error inesperado. Ni `physical_ready=true` ni una decisión JSON GO sustituyen la autorización humana operativa o inician movimiento. El estado vigente permanece `NO_GO_PENDING_REAL_HARDWARE_AND_HUMAN_REVIEW`.

## 19. Riesgos

Los riesgos principales son origen mal reproducido, extrínsecos erróneos, etiquetas manuales tardías, clock drift, oclusión, campo visual insuficiente, marcador flexible, instrumento sin precisión declarada, mezcla development/validation y uso accidental del joystick como verdad física. Cada riesgo requiere evidencia o exclusión explícita.

## 20. Checklist físico

- [ ] Fase, ID, ruta, orden y repeticiones aprobados.
- [ ] Zona y procedimiento HIL revisados por responsables físicos.
- [ ] Origen, +x, croquis y tolerancias documentados.
- [ ] Instrumentos y precisión confirmados.
- [ ] Hardware GT-CONT y montaje confirmados, o GT-MIN seleccionado.
- [ ] Extrínsecos necesarios medidos o declarados pendientes.
- [ ] Relojes y doble marcador de sincronización preparados.
- [ ] Directorio preparado y ejemplo validado.
- [ ] Operador y observador asignados; notas sin datos personales en Git.
- [ ] Criterios de aborto, almacenamiento y preservación de originales acordados.

## 21. Outputs esperados

Manifest, eventos, ficha/croquis de ruta, mediciones, calibraciones, tabla de sincronización, referencias externas si existen, reporte de validación JSON, inventario/hash de originales y reporte de métricas separado por fase. Ningún output implica por sí mismo readiness de odometría.

## 22. Estado de implementación

- Protocolo y contratos: preparados offline.
- `prepare_ground_truth_session.py`: implementado y probado en versión de herramientas 1.1.
- `validate_ground_truth_session.py`: implementa validación estructural exhaustiva de schema 1.0 y advertencias/bloqueos ante residuos o estados parciales.
- `assess_ground_truth_readiness.py`: implementado como evaluación read-only (exit codes: 0=GO, 2=NO_GO, 3=INVALID).
- `seal_ground_truth_preflight.py`: implementa el sellado transaccional con rollback (staging, backups y reemplazo ordenado de archivos en disco, con el manifest como commit point lógico y validación posterior).
- Schema `1.0`, route spec sellada e inventario físico: implementados.
- Revisión humana sellada, cruces de hashes, doble sync y rechazo de placeholders: implementados.
- Templates y tests standard-library: implementados.
- GT-MIN físico: pendiente de revisión y ejecución.
- GT-CONT: `PENDING_HARDWARE_CONFIRMATION`.
- Captura física, pose continua, odometría y frames físicos: no implementados/no validados.

## 23. Próximos pasos

Revisar físicamente recursos, tolerancias, seguridad, rutas y sincronización; seleccionar GT-MIN como nivel recomendado inicial; ejecutar primero CALIBRATION solo después de alcanzar GO. No usar sus pasadas para métricas finales.
