# docs/ - Raíz documental canónica de OttoGuide

## Estado documental

```text
DOCUMENTATION_ROOT = docs/
PROJECT_PHASE = FINAL_PROJECT_CLOSURE
BRANCH_RECONCILIATION = CLOSED
PRODUCTIVE_DEVELOPMENT = FROZEN
```

`docs/` es la única raíz documental canónica del repositorio. El objetivo de este índice es distinguir con claridad la autoridad vigente de cierre, la documentación técnica de referencia y la evidencia histórica.

No recrear `documentacion general del proyecto/`, `planificacion/` fuera de `docs/planning/`, ni nuevas raíces documentales por dominio.

## Precedencia vigente de cierre

1. `../AGENTS.md` - reglas operativas, seguridad y política Git.
2. `Arquitectura/CIERRE_FINAL_MVP.md` - contrato vigente de cierre y publicación.
3. `../README.md` - verdad pública del producto y de la evidencia.
4. `../TODO.md` - alcance diferido, limitaciones y validaciones futuras.
5. `Arquitectura/UNIFICACION_RAMAS_Y_HANDOFF.md` y `Arquitectura/unification-state.json` - gateways vigentes hacia provenance; los snapshots U-series byte-preservados viven en `Historico/Final_Closure_Predecessors/`.

Los `NEXT_ACTION`, R8, U3, U3C y roadmaps anteriores que aparezcan en documentos de provenance no son instrucciones activas durante `FINAL_PROJECT_CLOSURE`.

## Categorías presentes

| Carpeta | Rol en el cierre final |
|---|---|
| `Arquitectura/` | Contratos vigentes de cierre, decisiones arquitectónicas y provenance técnico. |
| `Operaciones_HIL/` | Runbooks y evidencia HIL/offline. Son referencia histórica o condicional; no autorizan una nueva sesión física. |
| `Hardware_Reference/` | Manuales y referencias del Unitree G1 EDU. |
| `AppPhone/` | Análisis pasivo de aplicaciones Unitree y plano factory. |
| `Auditorias/` | Informes y evidencia de auditorías históricas. |
| `audits/` | Evidencia/contratos técnicos Stage B conservados. |
| `Historico/` | Material archivado, snapshots, duplicados preservados y documentación no vigente. |
| `Investigacion/` | Investigación y prototipos exploratorios; no son claims de release por sí mismos. |
| `planning/` | Planificación V1/V2/V3 y matrices offline; material de planificación, no backlog activo de cierre. |
| `legacy/` | Código/documentación legada preservada con las restricciones de `AGENTS.md`. |

## Documentos actuales de cierre

| Documento | Función actual |
|---|---|
| `Arquitectura/CIERRE_FINAL_MVP.md` | Autoridad de cierre, sellado del árbol y publicación mirror/canonical/main. |
| `../README.md` | Contrato público de capacidades, límites y estado de release. |
| `../TODO.md` | Alcance fuera del cierre y validaciones futuras no reclamadas. |
| `../AGENTS.md` | Reglas operativas y gates de escritura/seguridad. |
| `Arquitectura/UNIFICACION_RAMAS_Y_HANDOFF.md` | Gateway vigente de provenance y reglas de reanudación del cierre; no contiene un roadmap U* activo. |
| `Arquitectura/unification-state.json` | Estado machine-readable compacto del cierre final; resuelve refs dinámicamente y enlaza el snapshot histórico. |
| `Historico/Final_Closure_Predecessors/` | Snapshots byte-preservados del handoff y estado U-series superseded como autoridad operativa. |
| `Arquitectura/ODOM_TF_R2_P2_FRAME_SEMANTICS_AND_COVARIANCE_CONTRACT.md` | Contrato P2 de frame/covarianza offline. |
| `Arquitectura/ODOM_TF_R2_P2A_CONTRACT_AUDIT_AND_HARDENING.md` | Auditoría/hardening P2A. |

## Documentación HIL y física

Los documentos bajo `Operaciones_HIL/` preservan procedimientos y evidencia acumulada. Durante el cierre final:

- una evidencia física histórica no recertifica el candidato actual;
- un runbook no constituye autorización para robot, SSH, DDS, Nav2, SLAM, audio o movimiento;
- cualquier nueva acción física requiere un checkpoint y autorización separados según `AGENTS.md`;
- el cierre del repositorio no requiere una nueva sesión física.

## Política de vigencia

1. `README.md` raíz resume el producto y el estado de release.
2. `TODO.md` raíz no es un backlog Post-RC1: registra únicamente alcance diferido y validaciones futuras.
3. `CIERRE_FINAL_MVP.md` gobierna el flujo final de sellado/publicación.
4. `UNIFICACION_RAMAS_Y_HANDOFF.md` y `unification-state.json` son gateways vigentes; la historia U-series completa se preserva byte-a-byte en `Historico/Final_Closure_Predecessors/` y queda subordinada al contrato de cierre.
5. Los documentos bajo `Historico/` son evidencia, no fuente operativa vigente sin revisión.
6. `Unitree Go` y `Unitree Explore` permanecen como referencias pasivas según la documentación arquitectónica; no forman una ruta activa de cierre.
7. Toda documentación propia vigente debe vivir bajo `docs/`, salvo `README.md`, `TODO.md`, `AGENTS.md` y READMEs locales estrictamente acoplados a código/configuración.
8. La raíz del repositorio se mantiene limitada a gobierno/documentación de entrada y las tres raíces estructurales establecidas: `docs/`, `codigo ottoguide/`, `ottoguide_web_app/`.
