# Runbook de Preflight CALIBRATION GT-MIN — OttoGuide

**Estado:** PREPARADO OFFLINE — NO AUTORIZA MOVIMIENTO

## 1. Objetivo

Evaluar de forma reproducible si una sesión `CALIBRATION` GT-MIN está estructuralmente preparada y qué bloqueos físicos impiden su ejecución.

## 2. Alcance

Este runbook solo prepara archivos y calcula GO/NO-GO declarativo. No conecta al robot, no ejecuta ROS, no mueve hardware y no inicia capturas.

## 3. Dependencias

Python 3 con standard library, checkout limpio, route spec schema `1.0`, inventario físico revisado y autorización humana independiente. No requiere paquetes adicionales.

## 4. Documentos fuente

- [PLAN_CAPTURA_GROUND_TRUTH_ODOMETRIA.md](PLAN_CAPTURA_GROUND_TRUTH_ODOMETRIA.md)
- [PROGRESO_ODOMETRIA_OFFLINE.md](PROGRESO_ODOMETRIA_OFFLINE.md)
- Templates en `codigo ottoguide/tools/hil/ground_truth/templates/`.

## 5. Hardware requerido

Instrumentos de distancia y ángulo con precisión conocida, marcas de piso/orientación, marcador de sincronización, almacenamiento, área supervisada y observador de seguridad. La disponibilidad actual no está confirmada.

## 6. Ruta y origen

Congelar `route_spec.json`, su revisión, segmentos, orden y tolerancias. Marcar el centro de `gt_robot` y +x; tolerancia provisional ±0.02 m y ±2°. Una desviación sin corrección medida implica `NOT_COMPARABLE`.

## 7. Instrumentos y precisión

Registrar nombre del instrumento y accuracy no negativa y finita en manifest, route spec e inventario. Una resolución comercial declarada sin revisión no prueba accuracy física.

## 8. Sincronización

Confirmar método, disponibilidad y accuracy esperada. Se requieren dos `SYNC_MARKER` con IDs distintos: uno entre `SESSION_START` y el primer `SEGMENT_START`, y otro entre el último `SEGMENT_END` y `SESSION_END`. Ambos declaran `time_tolerance_s` menor o igual a la accuracy del manifest e inventario y una fuente sin placeholders.

## 9. Preparación de sesión

```bash
python3 "codigo ottoguide/tools/hil/ground_truth/prepare_ground_truth_session.py" \
  <session_root> --session-id <id> \
  --route-spec "codigo ottoguide/tools/hil/ground_truth/templates/route_spec.example.json" \
  --experiment-phase CALIBRATION
```

El preparador copia la ruta a `calibration/route_spec.json`, registra SHA-256, genera schema `1.0` y deja `physical_readiness_status=NOT_REVIEWED`. Nunca genera GO.

Antes de validar readiness, completar un inventario y una revisión humana fuera de la sesión. Sellarlos explícitamente:

```bash
python3 "codigo ottoguide/tools/hil/ground_truth/seal_ground_truth_preflight.py" \
  <session_dir> <hardware_inventory.json> <human_review.json>
```

El sellador valida primero la sesión, copia ambos archivos a `calibration/`, calcula SHA-256 y registra paths, IDs y revisiones en el manifest mediante escrituras atómicas. Rechaza sobrescritura salvo `--force` y nunca cambia el status a GO. La route spec ya sellada no se modifica.

## 10. Validación estructural

Completar eventos y ejecutar:

```bash
python3 "codigo ottoguide/tools/hil/ground_truth/validate_ground_truth_session.py" \
  <session_dir>
```

El validador lee route spec, inventario y revisión desde el manifest. `ok=true` significa contrato y hashes válidos; no significa readiness física. Una alteración de cualquier evidencia sellada produce `decision=INVALID`.

## 11. Evaluación de readiness

```bash
python3 "codigo ottoguide/tools/hil/ground_truth/assess_ground_truth_readiness.py" \
  <session_dir>
```

El resultado es `INVALID`, `NO_GO` o `GO`. El script es read-only: no modifica manifest ni autoriza acciones.

| Exit code | Decisión | Significado |
|---:|---|---|
| 0 | `GO` | Todas las evidencias declaradas pasan; aún requiere autorización operativa humana inmediata |
| 2 | `NO_GO` | Estructura válida con uno o más bloqueos físicos/humanos |
| 3 | `INVALID` | Contrato, schema, referencia o hash inválido |
| 1 | error inesperado | Fallo de ejecución no clasificable |

## 12. Checklist humano

- [ ] Route spec revisada y aprobada para CALIBRATION por un rol autorizado.
- [ ] SHA y revisión coinciden con el manifest.
- [ ] Instrumentos presentes y accuracies documentadas.
- [ ] Inventario `REVIEWED_READY`, vigente, aplicable a la ruta y sellado por hash.
- [ ] Revisión humana sellada coincide con sesión, ruta e inventario.
- [ ] Marcas de piso, orientación y sincronización disponibles.
- [ ] Almacenamiento, área supervisada y observador confirmados.
- [ ] Eventos, tolerancias y doble sync revisados.
- [ ] Responsable humano emite autorización final por procedimiento HIL vigente.

## 13. Criterios GO

Contrato válido, manifest marcado GO por revisión humana, ruta aprobada para la fase, inventario `REVIEWED_READY` vigente y aplicable, instrumentos/precisiones consistentes, doble sync válido, origen dentro de tolerancia, almacenamiento, área y observador confirmados. Inventario y revisión deben estar sellados y sin placeholders críticos. Un GO JSON no inicia movimiento y no reemplaza la autorización humana operativa requerida inmediatamente antes de cualquier comando físico.

## 14. Criterios NO-GO

Cualquier requisito físico ausente, status `NOT_REVIEWED`/`NO_GO`, revisión ausente/NO-GO/inconsistente, inventario vencido, ruta no aprobada, placeholder crítico, origen no comprobado, sync incompleto, falta de almacenamiento/supervisión/observador o discrepancia no estructural pendiente. El estado actual es NO-GO.

## 15. Criterios de aborto

Abortar antes de capturar ante cambios de ruta posteriores al hash, origen fuera de tolerancia, instrumento distinto, sync no observable, almacenamiento insuficiente, pérdida de supervisión o cualquier condición de seguridad no aprobada. Durante una futura sesión física rige el protocolo HIL humano, no este script.

## 16. Preservación de originales

No editar bags, videos, poses externas ni mediciones originales. Registrar paths relativos, hashes e inventario; producir derivados en directorios separados. No subir evidencia pesada ni datos personales sin revisión.

## 17. Outputs

Manifest schema `1.0`, route spec sellada, eventos con tolerancias explícitas, inventario y revisión copiados/sellados, hashes de evidencia, resúmenes de sync/origen/revisión y reportes JSON.

## 18. Estado actual

Tooling y documentación: preparados offline con cierre fail-safe. Templates: `NO_GO`. Hardware y revisión humana reales: pendientes. `PHYSICAL_GO_NO_GO_STATUS=NO_GO_PENDING_REAL_HARDWARE_AND_HUMAN_REVIEW`. No se ejecutó CALIBRATION.
