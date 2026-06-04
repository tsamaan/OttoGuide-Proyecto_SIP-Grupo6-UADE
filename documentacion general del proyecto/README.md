# Indice Interno de Documentacion Tecnica - OttoGuide

Este directorio contiene la documentacion tecnica real del proyecto OttoGuide en estado `RC1_LOCKED`: arquitectura, operacion HIL, referencias de hardware, auditorias, analisis de aplicaciones Unitree y material historico.

Advertencia: el README maestro publico del proyecto vive en `../README.md` desde la raiz del repositorio. Este archivo es solo el indice documental interno de `documentacion general del proyecto/`.

## Indice de carpetas

| Carpeta | Proposito |
|---|---|
| `Arquitectura/` | Contratos tecnicos, memoria arquitectonica, frontera `ROS 2`/`DDS`/`SDK2` y analisis de integracion. |
| `Operaciones_HIL/` | Runbooks, protocolo fisico, preflight de sensores y procedimientos de despliegue/arranque. |
| `Hardware_Reference/` | Manuales y referencias tecnicas del Unitree G1 EDU. |
| `AppPhone/` | Analisis pasivo de `Unitree Go` y documentacion asociada al plano factory `192.168.12.x`. |
| `Auditorias/` | Informes de auditoria SRE y evidencias de revision documental/arquitectonica. |
| `Historico/` | Material archivado, duplicados preservados, snapshots y documentacion no vigente. |

## Documentos vigentes principales

| Documento | Uso |
|---|---|
| `Arquitectura/ARQUITECTURA_OPERATIVA_RC1.md` | Contrato operativo RC1 y flujo E2E. |
| `Arquitectura/ROS2_INTEGRATION.md` | Frontera entre Capa 4 Python, `ROS 2`, `DDS` y `SDK2`. |
| `Arquitectura/MEMORIA_ARQUITECTONICA_MVP.md` | Memoria academica y decisiones de diseno del MVP. |
| `Operaciones_HIL/README_codigo_ottoguide.md` | Indice operativo de codigo, `libs/` air-gapped y topologia HIL. |
| `Operaciones_HIL/HIL_TESTING_PROTOCOL.md` | Protocolo fisico HIL, seguridad, mapeo y apagado. |
| `Operaciones_HIL/PREFLIGHT_CERTIFICACION_SENSORES_PENDING.md` | Preflight de sensores y certificacion pendiente de validacion HIL fisica. |
| `Operaciones_HIL/RUNBOOK_LIVOX_SDK2_BRIDGE.md` | Build, arranque y validacion progresiva del bridge Livox SDK2 propio. |
| `Operaciones_HIL/RUNBOOK_STARTUP_RC1.md` | Secuencia de arranque y criterios GO/NO-GO. |
| `Operaciones_HIL/RUNBOOK_OPERACIONES_HIL_OTTOGUIDE.md` | Entrada vigente consolidada para operaciones HIL y siguiente sesion fisica. |
| `Operaciones_HIL/RUNBOOK_PROXIMA_SESION_FISICA_DDS_FOXY.md` | Runbook especifico para validar CycloneDDS Foxy en la proxima ventana fisica. |
| `Operaciones_HIL/RUNBOOK_PACKET_CAPTURE_HIL.md` | Captura pasiva del plano factory `192.168.12.x`. |
| `AppPhone/APK_CONNECTIVITY_ANALYSIS.codigo_ottoguide.md` | Analisis canonico del APK `Unitree Go` conservado como referencia factory pasiva. |

## Referencias historicas relevantes

| Documento | Uso |
|---|---|
| `Historico/Archivado_Documental_20260604_012123/Arquitectura/ANALISIS_UNITREE_EXPLORE_G1_AUTH.md` | Dictamen historico sobre `Unitree Explore`, AR8030, autenticacion y exclusion de ruta MVP. |
| `Historico/Archivado_Documental_20260604_012123/Arquitectura/ANALISIS_APK_COMPLETO_REPORT.md` | Analisis historico ampliado de `Unitree Go` y plano factory. |

## Politica de vigencia

1. `README.md` raiz resume el proyecto; este indice organiza la documentacion tecnica.
2. `TODO.md` raiz es backlog Post-RC1; no es runbook operativo.
3. Los documentos bajo `Historico/` se conservan como evidencia y no deben usarse como fuente operativa sin revision.
4. La ruta primaria de control G1 es `SDK2/DDS Unicast` hacia `192.168.123.161`.
5. El runtime HIL nativo esperado en la Companion PC G1 EDU es `ROS 2 Foxy`.
6. `Unitree Go` se documenta solo como referencia pasiva del plano factory; `Unitree Explore` es la app oficial G1/G1_D, pero no forma parte de la ruta MVP.