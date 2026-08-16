# OttoGuide — Limitaciones y continuidad futura

```text
TREE_CONTENT_STATUS = FINAL_RELEASE_TREE
PROJECT_PHASE = FINAL_PROJECT_CLOSED
CONTENT_RELEASE_BLOCKERS = 0
PRODUCTIVE_DEVELOPMENT = FROZEN
ACTIVE_PRODUCTIVE_NEXT_ACTION = NO_FURTHER_PRODUCTIVE_DEVELOPMENT
GIT_PUBLICATION_STATE = DYNAMIC_REMOTE_STATE_NOT_EMBEDDED
```

Este archivo **no es un backlog activo**. Aquí se registran únicamente límites, validaciones futuras y alcance deliberadamente excluido para evitar claims implícitos.

## Estados usados

- `CLOSED_FOR_RELEASE`: resuelto en el contenido final.
- `REQUIRES_FUTURE_PHYSICAL_VALIDATION`: sólo puede reabrirse en una fase/checkpoint HIL futuro.
- `DEFERRED_OUTSIDE_FINAL_SCOPE`: fuera del cierre académico.
- `NOT_CLAIMED`: no existe evidencia suficiente para reclamar la capacidad.
- `HISTORICAL_SUPERSEDED`: provenance conservada, no trabajo operativo vigente.

## Cerrado para release

- [CLOSED_FOR_RELEASE] Reconciliación de ramas: `review/orchestrator-unification` conserva la historia autoritativa; no hay merges mayoristas pendientes.
- [CLOSED_FOR_RELEASE] Contratos P2/P2A/P2C y sus límites de evidencia offline.
- [CLOSED_FOR_RELEASE] Gobierno final, documentación, seguridad y modelo `SINGLE_ROOT_FINAL_RELEASE`.
- [CLOSED_FOR_RELEASE] Backups transitorios CycloneDDS removidos del árbol final.
- [CLOSED_FOR_RELEASE] Estructura canónica: `docs/`, `codigo ottoguide/`, `ottoguide_web_app/`.

## Requiere validación física futura

- [REQUIRES_FUTURE_PHYSICAL_VALIDATION] Observar y validar `/odom`, `/tf`, `/tf_static`, `/map` y semántica de frames en el entorno Unitree objetivo.
- [REQUIRES_FUTURE_PHYSICAL_VALIDATION] Validar Nav2, SLAM/map y recorrido físico con operador, hardstop, límites y autorización HIL.
- [REQUIRES_FUTURE_PHYSICAL_VALIDATION] Validar bridges DDS/ROS, LiDAR, IMU, cámara y audio contra hardware real.
- [REQUIRES_FUTURE_PHYSICAL_VALIDATION] Generar evidencia física nueva antes de reclamar autonomía o deployment actual del árbol final.

Ninguna bloquea la entrega del proyecto académico.

## Fuera del alcance final

- [DEFERRED_OUTSIDE_FINAL_SCOPE] otros pisos o campus;
- [DEFERRED_OUTSIDE_FINAL_SCOPE] IA abierta ilimitada durante el recorrido estructurado;
- [DEFERRED_OUTSIDE_FINAL_SCOPE] integración con sistemas internos UADE;
- [DEFERRED_OUTSIDE_FINAL_SCOPE] soporte multiidioma;
- [DEFERRED_OUTSIDE_FINAL_SCOPE] nuevas features de producto;
- [DEFERRED_OUTSIDE_FINAL_SCOPE] rediseño de runtime;
- [DEFERRED_OUTSIDE_FINAL_SCOPE] expansión de CI no necesaria para el cierre;
- [DEFERRED_OUTSIDE_FINAL_SCOPE] reorganización cosmética del repositorio;
- [DEFERRED_OUTSIDE_FINAL_SCOPE] remerge de ramas laterales históricas.

## No reclamado

- [NOT_CLAIMED] ODOM/TF físicos actuales.
- [NOT_CLAIMED] Nav2/SLAM/autonomía física actual.
- [NOT_CLAIMED] recorrido Lima 3/Lima 2 físicamente validado por este tree.
- [NOT_CLAIMED] audio/cámara/DDS/ROS live del árbol final.
- [NOT_CLAIMED] equivalencia automática entre evidencia histórica y deployment actual.

## Histórico supersedido

- [HISTORICAL_SUPERSEDED] `RC1_LOCKED` y wording Post-RC1.
- [HISTORICAL_SUPERSEDED] R8/U3/U3C/P2C y antiguos `NEXT_ACTION`.
- [HISTORICAL_SUPERSEDED] ramas personales/laterales ya tratadas selectivamente durante la unificación.
- [HISTORICAL_SUPERSEDED] snapshots y runbooks cuya función actual es provenance.

## Seguridad

Este archivo no autoriza robot, SSH, DDS, Nav2, SLAM, audio, movimiento ni hardware. Cualquier continuidad futura debe abrirse explícitamente como una nueva fase/checkpoint y aplicar `AGENTS.md`.
