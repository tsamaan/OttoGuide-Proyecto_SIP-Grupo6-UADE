# docs/ — Raíz documental canónica de OttoGuide

```text
DOCUMENTATION_ROOT = docs/
TREE_CONTENT_STATUS = FINAL_RELEASE_TREE
PROJECT_PHASE = FINAL_PROJECT_CLOSED
BRANCH_RECONCILIATION = CLOSED
PRODUCTIVE_DEVELOPMENT = FROZEN
ACTIVE_PRODUCTIVE_NEXT_ACTION = NO_FURTHER_PRODUCTIVE_DEVELOPMENT
GIT_PUBLICATION_STATE = DYNAMIC_REMOTE_STATE_NOT_EMBEDDED
```

`docs/` es la única raíz documental propia. El estado remoto de publicación no se embebe aquí: para saber qué refs apuntan al árbol final debe consultarse GitHub.

## Precedencia

1. `../AGENTS.md` — operaciones, seguridad y Git.
2. `Arquitectura/CIERRE_FINAL_MVP.md` — contrato de cierre/publicación.
3. `../README.md` — verdad pública de producto y evidencia.
4. `../TODO.md` — limitaciones y continuidad futura.
5. `Arquitectura/UNIFICACION_RAMAS_Y_HANDOFF.md` y `Arquitectura/unification-state.json` — provenance y estado estable.
6. Evidencia histórica y ledgers — referencia, no instrucciones activas.

Los roadmaps `NEXT_ACTION`, R8, U3, U3C y P2C preservados históricamente no son trabajo pendiente.

## Categorías

| Carpeta | Función |
|---|---|
| `Arquitectura/` | contratos vigentes, decisiones, cierre y provenance técnico |
| `Operaciones_HIL/` | procedimientos y evidencia HIL/offline; no autorizan nuevas sesiones |
| `Hardware_Reference/` | referencias del Unitree G1 EDU |
| `AppPhone/` | análisis pasivos relacionados con Unitree |
| `Auditorias/` y `audits/` | auditorías/evidencia preservada |
| `Historico/` | material supersedido o archivado |
| `Investigacion/` | investigación/prototipos, no claims de release |
| `planning/` | planificación histórica, no backlog activo |
| `legacy/` | material legado preservado |

## Documentos de autoridad

| Documento | Rol |
|---|---|
| `../AGENTS.md` | política operativa y de seguridad |
| `../README.md` | alcance y claims públicos |
| `../TODO.md` | limitaciones/continuidad futura |
| `Arquitectura/CIERRE_FINAL_MVP.md` | protocolo durable de publicación final |
| `Arquitectura/UNIFICACION_RAMAS_Y_HANDOFF.md` | handoff final y provenance |
| `Arquitectura/unification-state.json` | estado machine-readable estable |
| `Historico/Final_Closure_Predecessors/` | snapshots U-series byte-preservados |
| `Arquitectura/ODOM_TF_R2_P2_FRAME_SEMANTICS_AND_COVARIANCE_CONTRACT.md` | contrato offline P2 |
| `Arquitectura/ODOM_TF_R2_P2A_CONTRACT_AUDIT_AND_HARDENING.md` | auditoría/hardening P2A |

## Evidencia HIL

La evidencia física histórica conserva provenance, pero no recertifica este árbol. Un runbook no autoriza robot, SSH, DDS, Nav2, SLAM, audio ni movimiento. El cierre documental/Git no requiere una nueva sesión física.

## Política documental

- No recrear `documentacion general del proyecto/`.
- No recrear `OttoGuide IA/`.
- No crear nuevas raíces documentales por pilar.
- Toda documentación propia futura debe integrarse bajo `docs/` salvo archivos raíz de gobierno o READMEs locales acoplados a código.
- `Historico/` contiene evidencia, no autoridad operativa por defecto.
- El árbol final se interpreta por la precedencia anterior, no por roadmaps históricos aislados.
