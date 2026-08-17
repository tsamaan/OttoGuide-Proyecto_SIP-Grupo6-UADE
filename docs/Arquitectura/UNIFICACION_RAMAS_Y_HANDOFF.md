# OttoGuide — Handoff final y provenance de ramas

## 1. Estado estable

```text
PROGRAM_OBJECTIVE = OTTOGUIDE_FINAL_PROJECT_CLOSURE
TREE_CONTENT_STATUS = FINAL_RELEASE_TREE
PROJECT_PHASE = FINAL_PROJECT_CLOSED
BRANCH_RECONCILIATION = CLOSED
PRODUCTIVE_DEVELOPMENT = FROZEN
ACTIVE_PRODUCTIVE_NEXT_ACTION = NO_FURTHER_PRODUCTIVE_DEVELOPMENT
GIT_PUBLICATION_STATE = DYNAMIC_REMOTE_STATE_NOT_EMBEDDED
CURRENT_EXTERNAL_MIRROR_DEPENDENCY = NONE
```

Este documento no es un roadmap U*. Es el gateway final de provenance para comprender cómo quedó consolidado OttoGuide sin depender de chats, workstations o ramas personales.

## 2. Orden de lectura

1. `AGENTS.md`
2. `README.md`
3. `TODO.md`
4. `docs/Arquitectura/CIERRE_FINAL_MVP.md`
5. `docs/Arquitectura/unification-state.json`
6. este handoff
7. snapshots/ledgers históricos sólo cuando se necesite reconstruir decisiones

## 3. Provenance U-series

Los estados U-series anteriores se preservan byte-a-byte en:

```text
docs/Historico/Final_Closure_Predecessors/UNIFICACION_RAMAS_Y_HANDOFF_U_SERIES_SUPERSEDED.md
docs/Historico/Final_Closure_Predecessors/unification-state-u-series-superseded.json
```

```text
HISTORICAL_PREDECESSORS = BYTE_PRESERVED_U_SERIES_PREDECESSORS_SUPERSEDED_AS_ACTIVE_AUTHORITY
```

Los `NEXT_ACTION`, U3/U3C, R8 y P2C contenidos allí son históricos.

## 4. Repositorios y roles

```text
CANONICAL_AUTHORITY = tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE
INTEGRATION_HISTORY = review/orchestrator-unification
FINAL_DELIVERY = main
FINAL_MAIN_MODEL = SINGLE_ROOT_FINAL_RELEASE
CURRENT_EXTERNAL_MIRROR_DEPENDENCY = NONE
WHOLESALE_BRANCH_MERGES = PROHIBITED
```

Los SHAs vivos del repositorio canónico siempre se resuelven desde GitHub. No se usa un SHA embebido como “HEAD actual”. Las referencias de staging y auditoría de etapas anteriores permanecen sólo en los predecessors históricos byte-preserved.

## 5. Resultado de reconciliación

La evolución histórica convergió en `review/orchestrator-unification`, que conserva la historia técnica autoritativa. Las ramas `robot`, `pilar-web`, `feature/erirobot`, `InteraccionIA`, `desarrollo`, `echezuria` y `teo` son provenance/fuentes históricas ya tratadas durante la unificación.

No deben volver a mergearse de forma mayorista para cerrar el proyecto.

```text
BRANCH_RECONCILIATION_REOPEN_REQUIRED = false
WHOLESALE_MERGES_REQUIRED = false
REBASE_REQUIRED = false
PRODUCTIVE_DEVELOPMENT_REOPEN_REQUIRED = false
```

## 6. Modelo de publicación

La política durable vigente es canónica y autocontenida:

```text
canonical final-tree audit
-> preserve immutable review history
-> root R with parents=[]
-> canonical/main lease/CAS
-> verify canonical root/tree/count invariants
```

Esto describe el procedimiento; no declara en qué paso está actualmente GitHub. Consultar sólo los refs canónicos para conocer el estado real; no hay dependencia operativa de un segundo repositorio.

## 7. Evidencia

El árbol puede contener implementación, tests y validación offline sin demostrar operación física actual.

No inferir ODOM/TF físicos, `/map` físico actual, autonomía Nav2, SLAM/map validado físicamente, tour completo, audio/cámara/DDS/ROS live ni autorización de robot/HIL.

La evidencia física histórica conserva provenance, no recertificación.

## 8. Alcance académico preservado

El diseño original contempló el piloto Lima 3/Lima 2 con cinco paradas y dejó fuera otros pisos/campus, IA abierta ilimitada durante la ruta, sistemas internos UADE y soporte multiidioma.

El alcance previsto no es evidencia física.

## 9. Reanudación futura

Si una sesión futura necesita conocer el estado de publicación canónico:

1. resolver live `review` y `main` del repositorio canónico;
2. verificar el root, tree y conteo de `main` contra la entrega canónica final auditada;
3. aplicar el protocolo de `CIERRE_FINAL_MVP.md` sólo si una curación canónica autorizada está pendiente;
4. no reabrir U3/U3C/R8/P2C;
5. no usar ramas históricas como backlog.

Para el producto:

```text
ACTIVE_PRODUCTIVE_NEXT_ACTION = NO_FURTHER_PRODUCTIVE_DEVELOPMENT
```
