# AGENTS.md — Reglas de Estructura del Repositorio OttoGuide

## Raíces canónicas

- `docs/` es la **única raíz documental** del repositorio. Toda documentación nueva debe crearse dentro de `docs/`.
- `codigo ottoguide/` es la **raíz del software**: código fuente, scripts, herramientas, configuración runtime, launch files y dependencias vendorizadas.

## Prohibiciones de estructura

- **No recrear** `documentacion general del proyecto/` en ninguna ruta ni profundidad.
- **No recrear** `planificacion/` como directorio independiente fuera de `docs/planning/`.
- **No crear nuevas raíces documentales por pilar** (por ejemplo `docs/domains/motion/`, `docs/domains/ai-voice/`, etc.); la reclasificación semántica profunda está diferida.
- **No crear** `docs/audit/`; la ruta canónica es `docs/audits/`.

## Cambios prohibidos sin autorización humana explícita

- **No modificar** el remote `canonical` (fetch ni push).
- **No abrir** pull requests contra `canonical`.
- **No hacer** force push, rebase ni squash de historia publicada.
- **No desplegar** código al robot físico sin protocolo HIL aprobado.

## Cambios de arquitectura

Cualquier cambio de arquitectura de software (orquestador, event bus, módulos runtime, interfaces DDS/ROS 2) requiere revisión humana antes de ser mergeado a `canonical`.

## Referencia de rama de revisión

La rama activa de integración es `review/orchestrator-unification` en el remote `mirror`.
El análisis de funcionalidades integradas, wiring del orquestador y tests pendientes se realiza sobre esa rama publicada.
