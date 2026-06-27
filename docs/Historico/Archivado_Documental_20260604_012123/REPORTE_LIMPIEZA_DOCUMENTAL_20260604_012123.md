# Reporte limpieza documental OttoGuide - 20260604_012123

## Alcance

Auditoria local de `documentacion general del proyecto/` en rama `robot`, sin acceso al robot fisico, sin tocar runtime, scripts, DDS, artifacts ni `codigo ottoguide/`.

Baseline Git observado antes de movimientos:

- HEAD: `66f3516`
- target-uade/robot: `66f3516`
- ahead/behind: `0 0`
- working tree inicial: limpio

## Inventario generado

Se generaron evidencias locales dentro de este directorio:

- `INVENTARIO_DOCUMENTAL_20260604_012123.txt`
- `INVENTARIO_MARKDOWN_20260604_012123.txt`
- `HASHES_MARKDOWN_20260604_012123.txt`
- `DUPLICADOS_EXACTOS_20260604_012123.txt`
- `RESUMEN_AppPhone_20260604_012123.txt`
- `RESUMEN_Arquitectura_20260604_012123.txt`
- `RESUMEN_Auditorias_20260604_012123.txt`
- `RESUMEN_Hardware_Reference_20260604_012123.txt`
- `RESUMEN_Historico_20260604_012123.txt`
- `RESUMEN_Investigacion_20260604_012123.txt`
- `RESUMEN_Operaciones_HIL_20260604_012123.txt`

## Duplicados exactos

| Hash | Archivos | Accion |
|---|---|---|
| `2824C3CDE6FC979B722281346B03C3C49DF0C03112E0DEFC600AA10CA2EB08AD` | `AppPhone/APK_CONNECTIVITY_ANALYSIS.codigo_ottoguide.md`; `Historico/Duplicados/APK_CONNECTIVITY_ANALYSIS.arquitectura_duplicado.md` | Sin movimiento. Ya existe una copia historica en `Historico/Duplicados`; se preserva la copia de `AppPhone` como referencia vigente/secundaria. |

## Clasificacion y acciones

| Archivo | Categoria actual | Clasificacion | Accion propuesta | Motivo | Destino |
|---|---|---|---|---|---|
| `Operaciones_HIL/RUNBOOK_OPERACIONES_HIL_OTTOGUIDE.md` | Operaciones_HIL | A. Vigente / mantener | Mantener y actualizar referencias historicas | Documento maestro vigente HIL; ahora referencia reportes archivados | Misma ubicacion |
| `Operaciones_HIL/RUNBOOK_PROXIMA_SESION_FISICA_DDS_FOXY.md` | Operaciones_HIL | A. Vigente / mantener | Mantener | Runbook especifico para proxima sesion fisica DDS Foxy | Misma ubicacion |
| `Operaciones_HIL/REPORTE_AUDITORIA_DOCUMENTAL_HIL_20260604.md` | Operaciones_HIL | B. Vigente referencial | Mantener | Evidencia de auditoria documental previa | Misma ubicacion |
| `Operaciones_HIL/RUNBOOK_LIVOX_SDK2_BRIDGE.md` | Operaciones_HIL | A. Vigente / mantener | Mantener | Runbook tecnico Livox SDK2 | Misma ubicacion |
| `Operaciones_HIL/RUNBOOK_STARTUP_RC1.md` | Operaciones_HIL | A. Vigente / mantener | Mantener | Startup operativo RC1 | Misma ubicacion |
| `Operaciones_HIL/PREFLIGHT_CERTIFICACION_SENSORES_PENDING.md` | Operaciones_HIL | A. Vigente / mantener | Mantener | Checklist pendiente de certificacion de sensores | Misma ubicacion |
| `Operaciones_HIL/REPORTE_HIL_BRIDGE_CRASH_SCAN_GATE_20260523.md` | Operaciones_HIL | C. Historico / mover | Movido con `git mv` | Bitacora fechada, no instruccion vigente; contexto consolidado por runbook maestro | `Historico/Operaciones_HIL_Reportes/REPORTE_HIL_BRIDGE_CRASH_SCAN_GATE_20260523.md` |
| `Operaciones_HIL/REPORTE_HIL_ODOM_BRIDGE_TIMED_MAPPING_20260527.md` | Operaciones_HIL | C. Historico / mover | Movido con `git mv` | Bitacora fechada, no instruccion vigente; contexto consolidado por runbook maestro | `Historico/Operaciones_HIL_Reportes/REPORTE_HIL_ODOM_BRIDGE_TIMED_MAPPING_20260527.md` |
| `Operaciones_HIL/REPORTE_HIL_ODOM_TF_AUDIT_20260526.md` | Operaciones_HIL | C. Historico / mover | Movido con `git mv` | Bitacora fechada, no instruccion vigente; contexto consolidado por runbook maestro | `Historico/Operaciones_HIL_Reportes/REPORTE_HIL_ODOM_TF_AUDIT_20260526.md` |
| `Operaciones_HIL/REPORTE_HIL_ODOMETER_SERVICE_SOURCE_AUDIT_20260527.md` | Operaciones_HIL | C. Historico / mover | Movido con `git mv` | Bitacora fechada, no instruccion vigente; contexto consolidado por runbook maestro | `Historico/Operaciones_HIL_Reportes/REPORTE_HIL_ODOMETER_SERVICE_SOURCE_AUDIT_20260527.md` |
| `Operaciones_HIL/REPORTE_HIL_SDK_STAGE_PROBES_20260523.md` | Operaciones_HIL | C. Historico / mover | Movido con `git mv` | Bitacora fechada, no instruccion vigente; contexto consolidado por runbook maestro | `Historico/Operaciones_HIL_Reportes/REPORTE_HIL_SDK_STAGE_PROBES_20260523.md` |
| `Operaciones_HIL/REPORTE_HIL_SVO_SUPERVISED_VALIDATION_PREP_20260527.md` | Operaciones_HIL | C. Historico / mover | Movido con `git mv` | Bitacora fechada, no instruccion vigente; contexto consolidado por runbook maestro | `Historico/Operaciones_HIL_Reportes/REPORTE_HIL_SVO_SUPERVISED_VALIDATION_PREP_20260527.md` |
| `Operaciones_HIL/REPORTE_HIL_UNITREE_HG_STATE_PROBE_20260527.md` | Operaciones_HIL | C. Historico / mover | Movido con `git mv` | Bitacora fechada, no instruccion vigente; contexto consolidado por runbook maestro | `Historico/Operaciones_HIL_Reportes/REPORTE_HIL_UNITREE_HG_STATE_PROBE_20260527.md` |
| `Operaciones_HIL/REPORTE_HIL_UNITREE_POSE_TWIST_SOURCE_AUDIT_20260527.md` | Operaciones_HIL | C. Historico / mover | Movido con `git mv` | Bitacora fechada, no instruccion vigente; contexto consolidado por runbook maestro | `Historico/Operaciones_HIL_Reportes/REPORTE_HIL_UNITREE_POSE_TWIST_SOURCE_AUDIT_20260527.md` |
| `Arquitectura/ANALISIS_APK_COMPLETO_REPORT.md` | Arquitectura | E. Redundante semantico / historico | Movido con `git mv` | Analisis APK/plano factory historico; no arquitectura operativa vigente | `Historico/Archivado_Documental_20260604_012123/Arquitectura/ANALISIS_APK_COMPLETO_REPORT.md` |
| `Arquitectura/ANALISIS_UNITREE_EXPLORE_G1_AUTH.md` | Arquitectura | E. Redundante semantico / historico | Movido con `git mv` | Dictamen Unitree Explore/AR8030 historico; no ruta operativa MVP | `Historico/Archivado_Documental_20260604_012123/Arquitectura/ANALISIS_UNITREE_EXPLORE_G1_AUTH.md` |
| `Arquitectura/ARQUITECTURA_OPERATIVA_RC1.md` | Arquitectura | A. Vigente / mantener | Mantener | Arquitectura operativa vigente | Misma ubicacion |
| `Arquitectura/MEMORIA_ARQUITECTONICA_MVP.md` | Arquitectura | A. Vigente / mantener | Mantener | Memoria arquitectonica MVP | Misma ubicacion |
| `Arquitectura/ROS2_INTEGRATION.md` | Arquitectura | A. Vigente / mantener | Mantener | Integracion ROS 2 vigente | Misma ubicacion |
| `Hardware_Reference/*` | Hardware_Reference | F. Referencia primaria | Mantener | Referencia/transcripcion de hardware; no consolidar ni mover salvo duplicado exacto | Misma ubicacion |
| `AppPhone/APK_CONNECTIVITY_ANALYSIS.codigo_ottoguide.md` | AppPhone | B. Vigente referencial | Mantener | Referencia secundaria AppPhone; duplicado exacto ya preservado en Historico/Duplicados | Misma ubicacion |
| `Auditorias/*` | Auditorias | B. Evidencia vigente referencial | Mantener | Auditoria como evidencia; no guia operativa directa | Misma ubicacion |
| `Historico/*` | Historico | C. Historico preservado | Mantener | Carpeta destino y preservacion de contexto | Misma ubicacion |

## Referencias actualizadas

- `documentacion general del proyecto/README.md`: se agregaron entradas para los runbooks HIL vigentes y una seccion de referencias historicas a los analisis APK/Unitree Explore movidos.
- `documentacion general del proyecto/Operaciones_HIL/RUNBOOK_OPERACIONES_HIL_OTTOGUIDE.md`: se actualizo la referencia de `REPORTE_HIL_*` a `Historico/Operaciones_HIL_Reportes/REPORTE_HIL_*`.

## Conservacion

No se borro ningun documento. Los archivos obsoletos o redundantes se movieron a `Historico/` con `git mv`.

No se tocaron:

- `codigo ottoguide/`
- runtime Python
- scripts HIL existentes
- configuracion DDS
- artifacts locales del bundle fisico
- `Hardware_Reference/*`

## Recomendacion

Revisar el diff completo y, si se aprueba la reorganizacion documental, commitear con:

```bash
git add -- "documentacion general del proyecto"
git commit -m "docs: archive redundant documentation and update HIL index"
```
