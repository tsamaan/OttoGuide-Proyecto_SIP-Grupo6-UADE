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

Confirmar método, disponibilidad y accuracy esperada. Cada `SYNC_MARKER` debe declarar `time_tolerance_s`; se requieren marcadores inicial y final según el plan.

## 9. Preparación de sesión

```bash
python3 "codigo ottoguide/tools/hil/ground_truth/prepare_ground_truth_session.py" \
  <session_root> --session-id <id> \
  --route-spec "codigo ottoguide/tools/hil/ground_truth/templates/route_spec.example.json" \
  --experiment-phase CALIBRATION
```

El preparador copia la ruta a `calibration/route_spec.json`, registra SHA-256, genera schema `1.0` y deja `physical_readiness_status=NOT_REVIEWED`. Nunca genera GO.

## 10. Validación estructural

Completar eventos y ejecutar:

```bash
python3 "codigo ottoguide/tools/hil/ground_truth/validate_ground_truth_session.py" \
  <session_dir> --hardware-inventory <hardware_inventory.json>
```

`ok=true` significa contrato estructural válido. No significa readiness física.

## 11. Evaluación de readiness

```bash
python3 "codigo ottoguide/tools/hil/ground_truth/assess_ground_truth_readiness.py" \
  <session_dir> <hardware_inventory.json>
```

El resultado es `INVALID`, `NO_GO` o `GO`. El script es read-only: no modifica manifest ni autoriza acciones.

## 12. Checklist humano

- [ ] Route spec revisada y aprobada para CALIBRATION por un rol autorizado.
- [ ] SHA y revisión coinciden con el manifest.
- [ ] Instrumentos presentes y accuracies documentadas.
- [ ] Marcas de piso, orientación y sincronización disponibles.
- [ ] Almacenamiento, área supervisada y observador confirmados.
- [ ] Eventos, tolerancias y doble sync revisados.
- [ ] Responsable humano emite autorización final por procedimiento HIL vigente.

## 13. Criterios GO

Contrato válido, manifest marcado GO por revisión humana, ruta aprobada para la fase, inventario válido, instrumentos y precisiones confirmados, sync disponible, almacenamiento, área y observador confirmados. Un GO JSON no inicia movimiento y no reemplaza autorización humana final.

## 14. Criterios NO-GO

Cualquier requisito físico ausente, status `NOT_REVIEWED`/`NO_GO`, ruta no aprobada, precisión desconocida, sync incompleto, falta de almacenamiento/supervisión/observador o discrepancia no estructural pendiente. El estado actual es NO-GO.

## 15. Criterios de aborto

Abortar antes de capturar ante cambios de ruta posteriores al hash, origen fuera de tolerancia, instrumento distinto, sync no observable, almacenamiento insuficiente, pérdida de supervisión o cualquier condición de seguridad no aprobada. Durante una futura sesión física rige el protocolo HIL humano, no este script.

## 16. Preservación de originales

No editar bags, videos, poses externas ni mediciones originales. Registrar paths relativos, hashes e inventario; producir derivados en directorios separados. No subir evidencia pesada ni datos personales sin revisión.

## 17. Outputs

Manifest schema `1.0`, route spec sellada, eventos con tolerancias explícitas, inventario, reporte estructural JSON, reporte readiness JSON y notas de revisión humana.

## 18. Estado actual

Tooling y documentación: preparados offline. Ejemplos: `NO_GO`. Hardware y revisión humana: pendientes. `PHYSICAL_GO_NO_GO_STATUS=NO_GO_PENDING_HARDWARE_AND_HUMAN_REVIEW`. No se ejecutó CALIBRATION.
