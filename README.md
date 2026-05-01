# OttoGuide MVP - RC1_LOCKED

Documento maestro de operacion y lectura rapida del proyecto.

---

## 1) Resumen Ejecutivo

OttoGuide es un sistema de guiado autonomo para recorridos en campus universitario.
En esta etapa MVP, el objetivo es operar en entorno real con robot fisico, no en simulacion.

El flujo E2E es simple de entender:
usuario da una orden -> el backend decide -> el stack de navegacion mueve al robot -> el sistema responde por voz y telemetria.

| Item | Definicion clara |
|---|---|
| Estado de release | RC1_LOCKED (freeze funcional activo) |
| Objetivo del MVP | Ejecutar tours autonomos con interaccion conversacional en hardware real |
| Plataforma fisica | Unitree G1 EDU 8 (HIL: Hardware In the Loop) |
| Backend de control | FastAPI asincrono |
| Middleware robotico | ROS 2 + CycloneDDS en modo unicast |
| Interfaz de operacion | Dashboard web SPA en Vanilla JS |
| Enfoque de seguridad | Preflight obligatorio + parada de emergencia API + parada manual |

---

## 2) Topologia de Directorios Actualizada

### 2.1 Arbol ASCII del repositorio

```text
OttoGuide-Proyecto_SIP-Grupo6-UADE/
|-- README.md
|-- codigo ottoguide/
|   |-- api/
|   |   |-- router.py
|   |   `-- schemas.py
|   |-- config/
|   |   |-- cyclonedds.xml
|   |   |-- nav2_params_g1.yaml
|   |   `-- settings.py
|   |-- data/
|   |   `-- mvp_tour_script.json
|   |-- deploy/
|   |   `-- ottoguide_mvp.service
|   |-- hardware/
|   |-- libs/
|   |-- logs/
|   |-- maps/
|   |-- resources/
|   |-- scripts/
|   |   |-- pre_deploy_cleanup.sh
|   |   |-- freeze_dependencies.sh
|   |   |-- cut_release.sh
|   |   |-- deploy_to_companion.sh
|   |   |-- bootstrap_target.sh
|   |   |-- sre_health_check.py
|   |   |-- preflight_check.sh
|   |   |-- verify_remote_env.sh
|   |   |-- start_robot.sh
|   |   `-- mvp_master_run.sh
|   |-- src/
|   |   |-- api/
|   |   |-- common/
|   |   |-- core/
|   |   |-- hardware/
|   |   |-- interaction/
|   |   |-- navigation/
|   |   `-- vision/
|   |-- static/
|   |   `-- dashboard.html
|   |-- tests/
|   |   |-- integration/
|   |   |-- mocks/
|   |   `-- unit/
|   |-- docker-compose.yml
|   |-- Dockerfile
|   |-- main.py
|   |-- pyproject.toml
|   `-- requirements_prod.txt
|-- documentacion general del proyecto/
|   |-- RC1_Vigente/
|   |   |-- ARQUITECTURA_OPERATIVA_RC1.md
|   |   |-- AUDITORIA_DOCUMENTAL_RC1.md
|   |   |-- RUNBOOK_STARTUP_RC1.md
|   |   |-- RUNBOOK_DEPLOY.md
|   |   |-- ROS2_INTEGRATION.md
|   |   `-- HIL_TESTING_PROTOCOL.md
|   |-- Historico_SITL/
|   |   |-- README_SITL_3D.md
|   |   `-- README_simulation.md
|   `-- Investigacion_y_Memorias/
|       |-- Investigacion.md
|       |-- MEMORIA_ARQUITECTONICA_MVP.md
|       |-- MEMORIA_TECNICA_EXPORT.txt
|       `-- G1-Manual-de-usuario-Transcripcion.md
`-- planificacion/
    |-- V2/
    `-- V3/
```

### 2.2 Responsabilidad estricta por directorio

| Directorio | Responsabilidad estricta (1 frase) |
|---|---|
| codigo ottoguide | Contiene el sistema ejecutable (API, logica, hardware y scripts de operacion). |
| codigo ottoguide/api | Expone contratos HTTP/WS para operar el tour y la seguridad del robot. |
| codigo ottoguide/config | Centraliza configuraciones de red robotica y parametros de navegacion. |
| codigo ottoguide/data | Guarda insumos funcionales del tour sin tocar codigo. |
| codigo ottoguide/deploy | Aloja artefactos de despliegue para companion/servicio. |
| codigo ottoguide/hardware | Abstrae la capa de control del robot real, mock y sim. |
| codigo ottoguide/scripts | Define la secuencia operativa y verificaciones de campo. |
| codigo ottoguide/src | Implementa el nucleo de negocio y los modulos E2E. |
| codigo ottoguide/static | Provee la interfaz web de monitoreo y control del operador. |
| codigo ottoguide/tests | Organiza validaciones unitarias, de integracion y dobles de prueba. |
| documentacion general del proyecto/RC1_Vigente | Es la unica base documental operativa para ejecutar RC1 en hardware. |
| documentacion general del proyecto/Historico_SITL | Conserva evidencia de simulacion previa como referencia historica. |
| documentacion general del proyecto/Investigacion_y_Memorias | Reune material academico, investigacion y anexos de contexto. |
| planificacion | Mantiene cronogramas y entregables de gestion del proyecto. |

---

## 3) Diccionario de Componentes

### 3.1 Mapeo tecnico -> funcion en mundo real

| Componente tecnico | Ubicacion principal | Rol en mundo real |
|---|---|---|
| FastAPI | codigo ottoguide/main.py + codigo ottoguide/api/router.py | Cerebro de decisiones y puerta de entrada de comandos. |
| CycloneDDS | codigo ottoguide/config/cyclonedds.xml | Red de mensajeria robotica que conecta procesos de control. |
| Nav2_bridge | codigo ottoguide/src/navigation/nav2_bridge.py | Control de movimiento seguro entre orden de ruta y locomocion real. |
| Vanilla JS (SPA) | codigo ottoguide/static/dashboard.html | Cabina del operador para observar estado y emitir acciones. |
| TourOrchestrator (FSM) | codigo ottoguide/src/core/tour_orchestrator.py | Director de la mision: decide cuando navegar, hablar o frenar. |
| ConversationManager | codigo ottoguide/src/interaction/conversation_manager.py | Asistente conversacional que transforma preguntas en respuestas audibles. |
| MissionAuditLogger | codigo ottoguide/src/core/mission_audit.py | Caja negra de operacion para trazabilidad y auditoria post-mision. |

### 3.2 Relacion con perfiles de lectura

| Perfil | Que debe mirar primero | Para que sirve |
|---|---|---|
| Gestion | Resumen Ejecutivo + Estado del Sistema | Entender valor, alcance y madurez RC1. |
| Operaciones | Roadmap de Ejecucion | Arrancar y operar el robot con criterio GO/NO-GO. |
| Tecnico | Diccionario + Matriz E2E | Diagnosticar flujo de datos y responsabilidades de modulo. |

---

## 4) Matriz de Interaccion E2E

### 4.1 Flujo de datos desde comando hasta accion fisica

| Paso | Origen | Modulo que actua | Canal | Salida observable |
|---|---|---|---|---|
| 1 | Operador (dashboard o API) | FastAPI Router | HTTP (ej. POST /tour/start) | Solicitud de mision aceptada/rechazada. |
| 2 | FastAPI Router | TourOrchestrator | Llamada asincrona interna | Estado pasa a NAVIGATING si valida precondiciones. |
| 3 | TourOrchestrator | Nav2_bridge | Corrutina + mensajes ROS 2 | Objetivos de navegacion publicados (waypoints). |
| 4 | Nav2/AMCL | Nav2_bridge | Topics ROS 2 | Planeamiento y velocidad calculada. |
| 5 | Nav2_bridge | Adaptador de hardware | Comando interno con limites | Velocidad clampeda y segura para locomocion. |
| 6 | Adaptador hardware | Unitree G1 EDU 8 | SDK + DDS unicast | Robot se mueve fisicamente segun ruta. |
| 7 | TourOrchestrator | ConversationManager | Corrutina (evento contextual) | Se genera respuesta textual/voz al usuario. |
| 8 | ConversationManager | Audio de salida | TTS local | Robot responde en voz durante o entre tramos. |
| 9 | TourOrchestrator | Dashboard | WebSocket (/ws/telemetry) | Operador ve estado, progreso y alertas en tiempo real. |
| 10 | TourOrchestrator | MissionAuditLogger | Registro JSON atomico | Evidencia completa para analisis posterior. |

### 4.2 Flujo de emergencia (siempre prioritario)

| Trigger | Ruta | Efecto inmediato |
|---|---|---|
| API de emergencia | POST /emergency | FSM pasa a EMERGENCY y aplica parada segura. |
| Control manual | Comando L1+A | Detencion manual de seguridad del hardware. |

---

## 5) Roadmap de Ejecucion (Startup Runbook)

Secuencia oficial para encender y operar el sistema fisico en RC1.

| # | Fase | Script/Accion | Criterio de salida |
|---|---|---|---|
| 1 | Preparacion de release | codigo ottoguide/scripts/pre_deploy_cleanup.sh | Workspace limpio y listo para congelar. |
| 2 | Congelado de dependencias | codigo ottoguide/scripts/freeze_dependencies.sh | Dependencias estabilizadas para target. |
| 3 | Corte de release | codigo ottoguide/scripts/cut_release.sh | Version candidata empaquetada. |
| 4 | Transferencia al companion | codigo ottoguide/scripts/deploy_to_companion.sh | Artefactos sincronizados en target. |
| 5 | Bootstrap de target | codigo ottoguide/scripts/bootstrap_target.sh | Entorno base operativo en companion PC. |
| 6 | Health check tecnico | codigo ottoguide/scripts/sre_health_check.py | Conectividad, modelo local y mapa en estado valido. |
| 7 | Gate preflight | codigo ottoguide/scripts/preflight_check.sh | Exit 0 para continuar; fallo critico bloquea. |
| 8 | Verificacion remota extendida | codigo ottoguide/scripts/verify_remote_env.sh | Exit 0 continua; Exit 1 bloqueo; Exit 2 solo con override. |
| 9 | Confirmacion de seguridad manual | Develop Mode + Position Mode en control del robot | Sin confirmacion manual no se autoriza arranque. |
| 10 | Arranque principal | codigo ottoguide/scripts/start_robot.sh | Sistema levantado con barreras de seguridad. |
| 11 | Orquestacion E2E (si aplica) | codigo ottoguide/scripts/mvp_master_run.sh | Stack completo para demo/operacion. |
| 12 | Verificacion post-arranque | GET /status + /ws/telemetry + dashboard | Operacion visible y trazable en tiempo real. |

### 5.1 GO / NO-GO operativo

| Control | GO | NO-GO |
|---|---|---|
| preflight_check.sh | Exit 0 | Cualquier error critico |
| verify_remote_env.sh | Exit 0 (o Exit 2 con autorizacion explicita) | Exit 1 |
| Estado de navegacion | ROS 2/Nav2 estables | Topics inestables o sin localizacion |
| Estado conversacional | Motor local disponible | Timeout o servicio no disponible |
| Seguridad del robot | Modos manuales confirmados | Confirmacion ausente |

---

## 6) Estado del Sistema (RC1 vs Expansion)

Leyenda: ✅ implementado y estable en RC1 | 🟡 en estabilizacion | ⏳ expansion futura

| Dominio | RC1 (Done) | Expansion futura (To-Do) |
|---|---|---|
| Operacion HIL en Unitree G1 | ✅ Flujo operativo activo con hardware real | ⏳ Ensayos de mayor duracion y carga operativa |
| Orquestacion de estados | ✅ FSM IDLE/NAVIGATING/INTERACTING/EMERGENCY activa | ⏳ KPIs avanzados por estado y alertas predictivas |
| Seguridad y parada | ✅ Parada por API + parada manual + barrera preflight | ⏳ Medicion formal de latencia de parada por escenario |
| Navegacion | ✅ Integracion Nav2/AMCL con bridge asincrono | ⏳ Automatizar pruebas de regresion de rutas |
| Interaccion conversacional | ✅ Pipeline local operativo para respuesta de guia | ⏳ Mejoras de contexto conversacional por zona del campus |
| Observabilidad | ✅ Estado por endpoint, telemetria WS y auditoria JSON | ⏳ Tablero de indicadores agregados para direccion |
| Documentacion estructural | ✅ Migracion a documentacion general del proyecto completada | ⏳ Curado periodico de historicos y anexos academicos |

---

## 7) Mapa de Documentos Vigentes

Solo se consideran vigentes para operacion RC1 los documentos bajo RC1_Vigente.

| Tipo | Ruta |
|---|---|
| Arquitectura vigente | documentacion general del proyecto/RC1_Vigente/ARQUITECTURA_OPERATIVA_RC1.md |
| Auditoria documental | documentacion general del proyecto/RC1_Vigente/AUDITORIA_DOCUMENTAL_RC1.md |
| Runbook de startup | documentacion general del proyecto/RC1_Vigente/RUNBOOK_STARTUP_RC1.md |
| Runbook de deploy | documentacion general del proyecto/RC1_Vigente/RUNBOOK_DEPLOY.md |
| Protocolo HIL | documentacion general del proyecto/RC1_Vigente/HIL_TESTING_PROTOCOL.md |
| Integracion ROS2 | documentacion general del proyecto/RC1_Vigente/ROS2_INTEGRATION.md |

Documentos en Historico_SITL e Investigacion_y_Memorias permanecen como soporte historico y academico, no como base operativa primaria.

---

## 8) Alcance y Restricciones RC1_LOCKED

| Regla | Aplicacion |
|---|---|
| Freeze funcional | No introducir cambios de codigo durante operacion RC1_LOCKED. |
| Cambios permitidos | Actualizaciones de documentacion y runbooks operativos. |
| Fuente de verdad operativa | Este README + carpeta documentacion general del proyecto/RC1_Vigente. |
