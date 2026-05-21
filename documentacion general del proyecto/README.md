# Índice Interno de Documentación Técnica - OttoGuide

Este directorio contiene la documentación técnica real del proyecto OttoGuide en estado `RC1_LOCKED`: arquitectura, operación HIL, referencias de hardware, auditorías, análisis de aplicaciones Unitree y material histórico.

Advertencia: el README maestro público del proyecto vive en `../README.md` desde la raíz del repositorio. Este archivo es solo el índice documental interno de `documentacion general del proyecto/`.

## Índice de carpetas

| Carpeta | Propósito |
|---|---|
| `Arquitectura/` | Contratos técnicos, memoria arquitectónica, frontera `ROS 2`/`DDS`/`SDK2` y análisis de integración. |
| `Operaciones_HIL/` | Runbooks, protocolo físico, preflight de sensores y procedimientos de despliegue/arranque. |
| `Hardware_Reference/` | Manuales y referencias técnicas del Unitree G1 EDU. |
| `AppPhone/` | Análisis pasivo de `Unitree Go` y documentación asociada al plano factory `192.168.12.x`. |
| `Auditorias/` | Informes de auditoría SRE y evidencias de revisión documental/arquitectónica. |
| `Historico/` | Material archivado, duplicados preservados, snapshots y documentación no vigente. |

## Documentos vigentes principales

| Documento | Uso |
|---|---|
| `Arquitectura/ARQUITECTURA_OPERATIVA_RC1.md` | Contrato operativo RC1 y flujo E2E. |
| `Arquitectura/ROS2_INTEGRATION.md` | Frontera entre Capa 4 Python, `ROS 2`, `DDS` y `SDK2`. |
| `Arquitectura/MEMORIA_ARQUITECTONICA_MVP.md` | Memoria académica y decisiones de diseño del MVP. |
| `Operaciones_HIL/README_codigo_ottoguide.md` | Índice operativo de código, `libs/` air-gapped y topología HIL. |
| `Operaciones_HIL/HIL_TESTING_PROTOCOL.md` | Protocolo físico HIL, seguridad, mapeo y apagado. |
| `Operaciones_HIL/PREFLIGHT_CERTIFICACION_SENSORES_PENDING.md` | Preflight de sensores y certificación pendiente de validación HIL física. |
| `Operaciones_HIL/RUNBOOK_LIVOX_SDK2_BRIDGE.md` | Build, arranque y validación progresiva del bridge Livox SDK2 propio. |
| `Operaciones_HIL/RUNBOOK_STARTUP_RC1.md` | Secuencia de arranque y criterios GO/NO-GO. |
| `Operaciones_HIL/RUNBOOK_PACKET_CAPTURE_HIL.md` | Captura pasiva del plano factory `192.168.12.x`. |
| `AppPhone/APK_CONNECTIVITY_ANALYSIS.codigo_ottoguide.md` | Análisis canónico del APK `Unitree Go` conservado como referencia factory pasiva. |
| `Arquitectura/ANALISIS_UNITREE_EXPLORE_G1_AUTH.md` | Dictamen sobre `Unitree Explore`, AR8030, autenticación y exclusión de ruta MVP. |

## Política de vigencia

1. `README.md` raíz resume el proyecto; este índice organiza la documentación técnica.
2. `TODO.md` raíz es backlog Post-RC1; no es runbook operativo.
3. Los documentos bajo `Historico/` se conservan como evidencia y no deben usarse como fuente operativa sin revisión.
4. La ruta primaria de control G1 es `SDK2/DDS Unicast` hacia `192.168.123.161`.
5. El runtime HIL nativo esperado en la Companion PC G1 EDU es `ROS 2 Foxy`.
6. `Unitree Go` se documenta solo como referencia pasiva del plano factory; `Unitree Explore` es la app oficial G1/G1_D, pero no forma parte de la ruta MVP.
