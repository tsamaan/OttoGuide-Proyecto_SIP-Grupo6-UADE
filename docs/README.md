# docs/ — Raíz Documental Canónica de OttoGuide

## Gobierno documental

`docs/` es la **única raíz documental canónica** de este repositorio.

- `docs/planning/` contiene planificación activa e histórica (`V1/`, `V2/`, `V3/`).
- `docs/audits/` contiene evidencias y auditorías técnicas.
- **No crear nuevamente** `documentacion general del proyecto/` en ninguna ruta.
- **No crear nuevamente** `planificacion/` en ninguna ruta.
- **No crear raíces documentales por dominio** fuera de `docs/` (por ejemplo `docs/domains/` está diferido).
- La reclasificación semántica profunda de documentos está diferida; la clasificación actual se conserva tal cual.

## Índice de categorías presentes

| Carpeta | Contenido |
|---|---|
| `Arquitectura/` | Contratos técnicos, memoria arquitectónica, frontera ROS 2/DDS/SDK2 y análisis de integración. |
| `Operaciones_HIL/` | Runbooks, protocolo físico, preflight de sensores, mapeo, replay offline y procedimientos de despliegue. |
| `Hardware_Reference/` | Manuales y referencias técnicas del Unitree G1 EDU. |
| `AppPhone/` | Análisis pasivo de `Unitree Go` y documentación del plano factory `192.168.12.x`. |
| `Auditorias/` | Informes de auditoría SRE y evidencias de revisión documental/arquitectónica. |
| `Historico/` | Material archivado, duplicados preservados, snapshots y documentación no vigente. |
| `Investigacion/` | Investigaciones y prototipos exploratorios. |
| `planning/` | Planificación del proyecto (V1, V2, V3). |
| `audits/` | Evidencias y contratos de auditoría técnica Stage B. |

---

Este directorio contiene la documentación técnica real del proyecto OttoGuide en estado `RC1_LOCKED`: arquitectura, operación HIL, referencias de hardware, auditorías, análisis de aplicaciones Unitree y material histórico.

El README maestro público del proyecto vive en `../README.md` desde la raíz del repositorio.

## Indice de carpetas

| Carpeta | Proposito |
|---|---|
| `Arquitectura/` | Contratos tecnicos, memoria arquitectonica, frontera `ROS 2`/`DDS`/`SDK2` y analisis de integracion. |
| `Operaciones_HIL/` | Runbooks, protocolo fisico, preflight de sensores, mapeo, replay offline y procedimientos de despliegue/arranque. |
| `Hardware_Reference/` | Manuales y referencias tecnicas del Unitree G1 EDU. |
| `AppPhone/` | Analisis pasivo de `Unitree Go` y documentacion asociada al plano factory `192.168.12.x`. |
| `Auditorias/` | Informes de auditoria SRE y evidencias de revision documental/arquitectonica. |
| `Historico/` | Material archivado, duplicados preservados, snapshots y documentacion no vigente. |

## Subcarpetas operativas HIL

| Carpeta | Uso |
|---|---|
| `Operaciones_HIL/Mapeo/` | Runbooks y reportes vigentes de captura/exportacion de mapas. |
| `Operaciones_HIL/Offline_Replay_SLAM/` | Replay local, sandbox Nav2 offline y planes de navegacion sin robot. |
| `Operaciones_HIL/Replay_RViz/` | Troubleshooting y visualizacion RViz para evidencia offline. |

## Documentos vigentes principales

| Documento | Uso |
|---|---|
| `Arquitectura/UNIFICACION_RAMAS_Y_HANDOFF.md` | Handoff canónico y portable para continuar la unificación de ramas desde `review/orchestrator-unification`. |
| `Arquitectura/ARQUITECTURA_OPERATIVA_RC1.md` | Contrato operativo RC1 y flujo E2E. |
| `Arquitectura/ROS2_INTEGRATION.md` | Frontera entre Capa 4 Python, `ROS 2`, `DDS` y `SDK2`. |
| `Arquitectura/MEMORIA_ARQUITECTONICA_MVP.md` | Memoria academica y decisiones de diseno del MVP. |
| `Arquitectura/ODOM_BRIDGE_CONTRACT.md` | Contrato offline del futuro `odom_bridge`, sin nodo ROS runtime ni validacion fisica. |
| `Arquitectura/OTTOGUIDE_HIL_ARCHITECTURE_AND_RUNTIME.md` | Topologia HIL, runtime observado y limites de seguridad. |
| `Arquitectura/ROBOT_FACTORY_BASELINE_AND_OTTOGUIDE_EVOLUTION.md` | Baseline factory y evolucion controlada hacia OttoGuide. |
| `Operaciones_HIL/README_codigo_ottoguide.md` | Indice operativo de codigo, `libs/` air-gapped y topologia HIL. |
| `Operaciones_HIL/HIL_TESTING_PROTOCOL.md` | Protocolo fisico HIL, seguridad, mapeo y apagado. |
| `Operaciones_HIL/PREFLIGHT_CERTIFICACION_SENSORES_PENDING.md` | Preflight de sensores y certificacion pendiente de validacion HIL fisica. |
| `Operaciones_HIL/PREFLIGHT_PROXIMA_SESION_FISICA_ODOM_TF.md` | Preflight read-only para descubrir fuente real de TF/odom sin mover robot. |
| `Operaciones_HIL/RUNBOOK_LIVOX_SDK2_BRIDGE.md` | Build, arranque y validacion progresiva del bridge Livox SDK2 propio. |
| `Operaciones_HIL/OTTOGUIDE_MAP_EXECUTABLE_QUICKSTART.md` | Quickstart del ejecutable `ottoguide-map` para captura/mapeo supervisado. |
| `Operaciones_HIL/ODOM_TF_OFFLINE_ANALYSIS_20260618.md` | Analisis offline ODOM/TF y proximos pasos seguros. |
| `Operaciones_HIL/Offline_Replay_SLAM/PROGRESO_ODOMETRIA_OFFLINE.md` | Registro consolidado y actualizable del trabajo de odometría offline. |
| `Operaciones_HIL/Offline_Replay_SLAM/PLAN_CAPTURA_GROUND_TRUTH_ODOMETRIA.md` | Protocolo reproducible de ground truth segmentario y continuo para validar odometría offline. |
| `Operaciones_HIL/Offline_Replay_SLAM/RUNBOOK_CALIBRATION_GT_MIN_PREFLIGHT.md` | Runbook offline de contrato y readiness físico para una futura CALIBRATION GT-MIN. |
| `Operaciones_HIL/RUNBOOK_STARTUP_RC1.md` | Secuencia de arranque y criterios GO/NO-GO. |
| `Operaciones_HIL/RUNBOOK_OPERACIONES_HIL_OTTOGUIDE.md` | Entrada vigente consolidada para operaciones HIL y siguiente sesion fisica. |
| `Operaciones_HIL/RUNBOOK_PROXIMA_SESION_FISICA_DDS_FOXY.md` | Runbook especifico para validar CycloneDDS Foxy en la proxima ventana fisica. |
| `Operaciones_HIL/RUNBOOK_PACKET_CAPTURE_HIL.md` | Captura pasiva del plano factory `192.168.12.x`. |
| `Auditorias/LOCAL_ARTIFACTS_AUDIT_RUNBOOK.md` | Procedimiento read-only para auditar artifacts locales ignorados por Git. |
| `Auditorias/ROBOT_NETWORK_PORTS_API_INVENTORY.md` | Inventario de red, puertos y APIs observadas. |
| `Auditorias/ROBOT_REAL_VALIDATION_FOR_MOVEMENT_DOC.md` | Evidencia parcial real para documentacion de movimiento sin afirmar autonomia. |
| `AppPhone/APK_CONNECTIVITY_ANALYSIS.codigo_ottoguide.md` | Analisis canonico del APK `Unitree Go` conservado como referencia factory pasiva. |

## Referencias historicas relevantes

| Documento | Uso |
|---|---|
| `Historico/Archivado_Documental_20260604_012123/Arquitectura/ANALISIS_UNITREE_EXPLORE_G1_AUTH.md` | Dictamen historico sobre `Unitree Explore`, AR8030, autenticacion y exclusion de ruta MVP. |
| `Historico/Archivado_Documental_20260604_012123/Arquitectura/ANALISIS_APK_COMPLETO_REPORT.md` | Analisis historico ampliado de `Unitree Go` y plano factory. |
| `Historico/Operaciones_HIL_Reportes/GitOps/GITHUB_ROBOT_BRANCH_VALIDATION.md` | Validacion Git historica de `fad510f`; obsoleta frente a HEAD posterior. |
| `Historico/Operaciones_HIL_Reportes/` | Reportes HIL fechados, evidencias RViz y documentos de handoff preservados. |

## Politica de vigencia

1. `README.md` raiz resume el proyecto; este indice organiza la documentacion tecnica.
2. `TODO.md` raiz es backlog Post-RC1; no es runbook operativo.
3. Los documentos bajo `Historico/` se conservan como evidencia y no deben usarse como fuente operativa sin revision.
4. La ruta primaria de control G1 es `SDK2/DDS Unicast` hacia `192.168.123.161`.
5. El runtime HIL nativo esperado en la Companion PC G1 EDU es `ROS 2 Foxy`.
6. `Unitree Go` se documenta solo como referencia pasiva del plano factory; `Unitree Explore` es la app oficial G1/G1_D, pero no forma parte de la ruta MVP.
7. Toda documentación propia vigente debe vivir bajo `docs/`, salvo `README.md`, `TODO.md` y READMEs locales estrictamente acoplados a código/configuración.
8. La raíz del repositorio se mantiene limpia: código, tooling, launch files y configuración runtime propia viven bajo `codigo ottoguide/`.
