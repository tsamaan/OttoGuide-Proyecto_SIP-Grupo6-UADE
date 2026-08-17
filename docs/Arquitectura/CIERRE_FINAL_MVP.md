# OttoGuide — Contrato final de cierre y publicación del MVP

## 1. Estado estable del contenido

```text
PROGRAM_OBJECTIVE = OTTOGUIDE_FINAL_PROJECT_CLOSURE
TREE_CONTENT_STATUS = FINAL_RELEASE_TREE
PROJECT_PHASE = FINAL_PROJECT_CLOSED
BRANCH_RECONCILIATION = CLOSED
PRODUCTIVE_DEVELOPMENT = FROZEN
ACTIVE_PRODUCTIVE_NEXT_ACTION = NO_FURTHER_PRODUCTIVE_DEVELOPMENT
GIT_PUBLICATION_STATE = DYNAMIC_REMOTE_STATE_NOT_EMBEDDED
FINAL_RELEASE_MODEL = SINGLE_ROOT_FINAL_RELEASE
CANONICAL_REPOSITORY = tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE
CURRENT_EXTERNAL_MIRROR_DEPENDENCY = NONE
```

Este documento define el contrato durable de entrega. No registra qué ref remoto apunta actualmente a este árbol: esa condición cambia fuera del contenido y debe verificarse directamente en GitHub.

El SHA exacto de `SEALED_FINAL_TREE` pertenece a la auditoría externa del checkpoint; no se autoembebe dentro del propio tree.

## 2. Autoridad y provenance

Orden de interpretación:

1. `AGENTS.md`;
2. este documento;
3. `README.md`;
4. `TODO.md`;
5. `UNIFICACION_RAMAS_Y_HANDOFF.md` y `unification-state.json`;
6. ledgers, snapshots U-series y documentación histórica.

Los antiguos `NEXT_ACTION`, R8, U3, U3C y P2C son provenance. No reabren trabajo productivo.

## 3. Alcance académico

El release es un cierre académico demostrable, no una certificación de producción.

Clasificaciones válidas:

- `IMPLEMENTADO`;
- `VALIDADO_OFFLINE`;
- `VALIDADO_FISICAMENTE_HISTORICO`;
- `NO_VALIDADO_EN_ARBOL_FINAL`;
- `FUERA_DEL_ALCANCE_FINAL_MVP`;
- `RIESGO_RESIDUAL_O_CONTINUIDAD_FUTURA`.

Una validación offline no prueba comportamiento físico y la evidencia física histórica no recertifica automáticamente el árbol final.

El MVP original contempló un piloto UADE Monserrat por Lima 3/Lima 2 con cinco paradas, IA local durante el recorrido estructurado e interacción libre al final.

Exclusiones deliberadas:

- otros pisos o campus;
- IA abierta ilimitada durante el recorrido estructurado;
- integración con sistemas internos UADE;
- soporte multiidioma.

## 4. Estructura final

```text
docs/                  documentación y evidencia
codigo ottoguide/      runtime, robótica, integración, herramientas y tests
ottoguide_web_app/     aplicación web integrada
```

No se requiere reorganización estructural tardía. Las raíces históricas supersedidas no deben recrearse.

## 5. Modelo de ramas

```text
review/orchestrator-unification
    historia completa de desarrollo e integración autoritativa

main
    entrega final: un único commit raíz sin padres

feature/odom-tf-r2-p2-frame-semantics-covariance-contract
    provenance histórica; no autoridad durable

ramas laterales y audit/*
    provenance histórica; no merges mayoristas
```

La reconciliación histórica está cerrada. `main` no se mergea ni rebasea con `review`.

## 6. Contrato del árbol final

```text
CANONICAL_MAIN_TREE = FINAL_CANONICAL_DELIVERY_TREE
parents(CANONICAL_MAIN_ROOT) = []
CANONICAL_MAIN_COMMIT_COUNT = 1
```

`review` conserva la genealogía integrada byte-a-byte; `main` conserva el snapshot académico final curado. Sus árboles pueden diferir cuando una corrección documental de entrega no modifica `review`.

## 7. Protocolo durable de publicación

El procedimiento vigente es canónico y no es un `NEXT_ACTION` embebido:

```text
audit exact canonical delivery tree
        |
        v
verify review/orchestrator-unification remains immutable
        |
        v
create root R with parents(R) = []
        |
        v
canonical/main lease/CAS guarded replacement
        |
        v
verify canonical root/tree/count invariants
```

Cada operación debe resolver refs frescos y fallar cerrada ante drift.

## 8. Placeholder histórico de `main`

La precondición histórica de cierre fue:

```text
LEGACY_MAIN_SHA = 3a1f13574e4a27d9aff2bfd38b3659951e8cb264
LEGACY_MAIN_TREE = 4b825dc642cb6eb9a060e54bf8d69288fbee4904
LEGACY_MAIN_PARENT_COUNT = 0
```

Son provenance/precondición histórica. Antes de cualquier reemplazo de `main` deben revalidarse live; este documento no afirma que sigan siendo el estado remoto actual.

No mergear ni rebasear contra ese placeholder.

## 9. Seguridad Git

`BLIND_FORCE = PROHIBITED`.

El reemplazo de `canonical/main` por un root final curado es una excepción acotada al fast-forward y sólo es válido si:

- el ref remoto coincide con la precondición esperada;
- el árbol final exacto fue auditado;
- se usa lease o compare-and-swap equivalente;
- existe autorización explícita fresca para la escritura canónica;
- cualquier diferencia de SHA/tree aborta.

No tags, rebases, merges mayoristas ni reescritura de `review` durante el cierre.

## 10. Claims físicos

Este árbol no afirma validación física actual de `/odom`, `/tf`, `/tf_static`, `/map`, Nav2, SLAM/map, recorrido completo, audio/cámara, DDS/ROS live ni deployment del tree exacto.

Cualquier revalidación física futura es una fase/checkpoint separado.

## 11. Definición de publicación correcta

Una verificación remota externa del repositorio canónico debe demostrar:

```text
CANONICAL_REVIEW = historia integrada preservada
CANONICAL_MAIN_TREE = FINAL_CANONICAL_DELIVERY_TREE
CANONICAL_MAIN_PARENT_COUNT = 0
CANONICAL_MAIN_COMMIT_COUNT = 1
CURRENT_EXTERNAL_MIRROR_DEPENDENCY = NONE
```

Esa evidencia es remota y temporal; no se autoafirma dentro del tree.

El contenido estable del proyecto es:

```text
TREE_CONTENT_STATUS = FINAL_RELEASE_TREE
PROJECT_PHASE = FINAL_PROJECT_CLOSED
PRODUCTIVE_DEVELOPMENT = FROZEN
ACTIVE_PRODUCTIVE_NEXT_ACTION = NO_FURTHER_PRODUCTIVE_DEVELOPMENT
```
