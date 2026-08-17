# Reporte Auditoria Documental HIL - 2026-06-04

## 1. Alcance

Auditoria local de documentacion OttoGuide, sin robot fisico, sin SSH, sin ROS y sin cambios runtime.

Objetivos:

- inventariar Markdown del proyecto;
- detectar duplicados exactos y redundancias semanticas;
- ubicar el runbook DDS Foxy en `documentacion general del proyecto/Operaciones_HIL`;
- crear documento maestro HIL sin borrar historicos.

## 2. Inventario

- Markdown total leidos en `documentacion general del proyecto`: 32
- Markdown leidos en `Operaciones_HIL`: 16
- Runbook nuevo leido originalmente desde ubicacion temporal; fuente vigente: `documentacion general del proyecto/Operaciones_HIL/RUNBOOK_PROXIMA_SESION_FISICA_DDS_FOXY.md`

## 3. Duplicados exactos

| SHA256 | Archivos |
|---|---|
| `2824C3CDE6FC979B722281346B03C3C49DF0C03112E0DEFC600AA10CA2EB08AD` | `AppPhone/APK_CONNECTIVITY_ANALYSIS.codigo_ottoguide.md`; `Historico/Duplicados/APK_CONNECTIVITY_ANALYSIS.arquitectura_duplicado.md` |

No se borraron duplicados.

## 4. Redundancias semanticas

| Grupo | Archivos | Diagnostico | Accion recomendada |
|---|---|---|---|
| Operacion HIL general | `HIL_TESTING_PROTOCOL.md`, `RUNBOOK_STARTUP_RC1.md`, `README_codigo_ottoguide.md` | Solapan fases, seguridad y arranque RC1 | Mantener historicos; usar `RUNBOOK_OPERACIONES_HIL_OTTOGUIDE.md` como entrada vigente |
| Sensores/mapeo | `PREFLIGHT_CERTIFICACION_SENSORES_PENDING.md`, `RUNBOOK_LIVOX_SDK2_BRIDGE.md`, reportes scan/odom | Complementarios por fase; no duplicados exactos | Consolidar criterios vigentes en maestro, preservar reportes |
| DDS/red | `ARQUITECTURA_OPERATIVA_RC1.md`, `ROS2_INTEGRATION.md`, `README_codigo_ottoguide.md`, nuevo runbook DDS | Red/DDS repetidos en varios niveles | Maestro HIL concentra estado operativo; arquitectura queda como contexto |
| App factory/Unitree Go | `AppPhone/*`, `ANALISIS_APK_COMPLETO_REPORT.md`, `Historico/Duplicados/*` | Plano factory historico, no ruta primaria | Preservar como historico/secundario |
| Odometria/SVO/Unitree DDS | `REPORTE_HIL_UNITREE_*`, `REPORTE_HIL_ODOM*`, `REPORTE_HIL_SVO*` | Bitacoras por evidencia, no instrucciones vigentes | Preservar como historico; no fusionar destructivamente |

## 5. Clasificacion documental

### Mantener como fuente vigente

- `RUNBOOK_OPERACIONES_HIL_OTTOGUIDE.md`
- `RUNBOOK_PROXIMA_SESION_FISICA_DDS_FOXY.md`
- `RUNBOOK_LIVOX_SDK2_BRIDGE.md`
- `RUNBOOK_STARTUP_RC1.md`
- `PREFLIGHT_CERTIFICACION_SENSORES_PENDING.md`

### Consolidar en documento maestro

- `HIL_TESTING_PROTOCOL.md`
- `README_codigo_ottoguide.md`
- `ARQUITECTURA_OPERATIVA_RC1.md`
- `ROS2_INTEGRATION.md`
- reportes HIL recientes de DDS/Livox/odom/SVO

### Preservar como historico

- `REPORTE_HIL_*`
- `AppPhone/*`
- `Historico/*`
- `Hardware_Reference/*`
- `Auditorias/AUDITORIA_LIDAR_EXPLORE_ELECTROSIM.md`

### Obsoleto/redundante, no borrar todavia

- `Historico/Duplicados/APK_CONNECTIVITY_ANALYSIS.arquitectura_duplicado.md`

### Requiere revision humana

- `RUNBOOK_DEPLOY.md` no tiene H1 y parece incompleto/minimo.
- `README_SITL_3D.md` no tiene H1.

## 6. Documentos creados

- `documentacion general del proyecto/Operaciones_HIL/RUNBOOK_PROXIMA_SESION_FISICA_DDS_FOXY.md`
- `documentacion general del proyecto/Operaciones_HIL/RUNBOOK_OPERACIONES_HIL_OTTOGUIDE.md`
- `documentacion general del proyecto/Operaciones_HIL/REPORTE_AUDITORIA_DOCUMENTAL_HIL_20260604.md`

## 7. Archivos no tocados

- runtime Python;
- scripts HIL existentes;
- `codigo ottoguide/config/cyclonedds.xml`;
- `codigo ottoguide/cyclonedds.xml`;
- artifacts locales;
- reportes historicos existentes.

## 8. Recomendacion Git

Stagear solo:

```text
documentacion general del proyecto/Operaciones_HIL/RUNBOOK_PROXIMA_SESION_FISICA_DDS_FOXY.md
documentacion general del proyecto/Operaciones_HIL/RUNBOOK_OPERACIONES_HIL_OTTOGUIDE.md
documentacion general del proyecto/Operaciones_HIL/REPORTE_AUDITORIA_DOCUMENTAL_HIL_20260604.md
```

Mensaje sugerido:

```text
docs(hil): consolidate physical session runbooks
```
