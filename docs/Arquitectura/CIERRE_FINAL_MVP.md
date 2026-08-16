# OttoGuide — Contrato vigente de cierre final del MVP

## 1. Propósito

Este documento define la capa de autoridad vigente para cerrar y publicar el proyecto académico OttoGuide sin reinterpretar como trabajo pendiente los microcheckpoints históricos de desarrollo e integración.

```text
PROGRAM_OBJECTIVE = OTTOGUIDE_FINAL_PROJECT_CLOSURE
PROJECT_PHASE = FINAL_PROJECT_CLOSURE
BRANCH_RECONCILIATION = CLOSED
PRODUCTIVE_DEVELOPMENT = FROZEN
FINAL_RELEASE_MODEL = SINGLE_ROOT_FINAL_RELEASE
```

Su objetivo es preservar toda la evidencia acumulada y, al mismo tiempo, expresar una única verdad operativa sobre qué falta para la entrega final.

## 2. Autoridad y relación con la documentación histórica

Para el cierre actual:

- `AGENTS.md` gobierna operaciones, seguridad y Git;
- este documento gobierna el contrato de cierre y publicación;
- `README.md` comunica la verdad pública del producto;
- `TODO.md` distingue bloqueantes reales de continuidad futura;
- `docs/Arquitectura/UNIFICACION_RAMAS_Y_HANDOFF.md`, `docs/Arquitectura/unification-state.json` y los documentos R/U/P2C conservan provenance, decisiones y evidencia histórica.

Los valores históricos `NEXT_ACTION`, R8, U3, U3C y otros microcheckpoints que sigan apareciendo en esos ledgers **no constituyen una instrucción activa** durante `FINAL_PROJECT_CLOSURE`. No se eliminan porque son parte de la trazabilidad del proyecto. La sección `final_release_governance` del estado de unificación y este contrato definen la semántica vigente.

Esto evita dos errores opuestos:

1. borrar o reescribir evidencia histórica sólo para que parezca actual;
2. interpretar una hoja de ruta histórica como obligación de seguir desarrollando antes de entregar.

## 3. Alcance final del MVP

El release final es un cierre académico demostrable, no una certificación de producción ni una promesa de completar toda línea experimental investigada durante el proyecto.

Las capacidades y evidencias deben clasificarse con una de estas etiquetas:

- `IMPLEMENTADO`;
- `VALIDADO_OFFLINE`;
- `VALIDADO_FISICAMENTE_HISTORICO`;
- `NO_VALIDADO_EN_CANDIDATO_ACTUAL`;
- `FUERA_DEL_ALCANCE_FINAL_MVP`;
- `RIESGO_RESIDUAL_O_CONTINUIDAD_FUTURA`.

`README.md`, los tests y los documentos de evidencia determinan la clasificación concreta de cada capacidad. Este contrato no eleva el nivel de evidencia de ninguna de ellas.

En particular:

- una validación offline no equivale a validación física actual;
- una validación física registrada históricamente conserva valor de evidencia, pero no recertifica automáticamente el candidato actual;
- una capacidad investigada o parcialmente implementada no se reclama como funcionalidad final si no tiene evidencia suficiente;
- una tarea futura registrada en `TODO.md` no es un release blocker salvo que esté explícitamente clasificada como tal.

## 4. Decisión deliberada de alcance

Las capacidades que requerirían nuevas sesiones físicas, una ampliación material del calendario académico, riesgo operativo adicional o una nueva fase de desarrollo desproporcionada respecto del objetivo de la entrega pueden quedar deliberadamente fuera del alcance final.

Esto no las convierte en defectos ocultos ni en capacidades implícitamente prometidas. Deben permanecer documentadas como limitación, riesgo residual o continuidad futura según corresponda.

La prioridad del cierre es entregar un incremento coherente, trazable, reproducible y defendible con la evidencia realmente disponible.

## 5. Modelo real del repositorio

Las raíces vigentes son:

```text
docs/                 documentación única y evidencia versionada
codigo ottoguide/      núcleo robótico, runtime, integración, herramientas y tests
ottoguide_web_app/      aplicación web integrada
```

No se realizará una reorganización estructural tardía sólo para satisfacer una clasificación histórica de raíces. Los movimientos sólo se justifican si una auditoría demuestra un bloqueante material para la entrega.

## 6. Modelo de ramas

```text
feature/odom-tf-r2-p2-frame-semantics-covariance-contract
    candidato de cierre y remediaciones finales acotadas

review/orchestrator-unification
    historia de integración y línea técnica autoritativa

main
    entrega final, no base de integración
```

Las decisiones de reconciliación de ramas históricas están cerradas. Las ramas laterales se conservan como provenance o fuentes selectivas históricas; no existe autorización para merges mayoristas.

## 7. Gates restantes de publicación

El camino de cierre es finito:

```text
candidato en mirror feature
        |
        v
auditoría remota independiente
        |
        v
mirror/review fast-forward
        |
        v
verificación independiente
        |
        v
canonical/review fast-forward exacto
        |
        v
verificación de igualdad mirror/canonical
        |
        v
SEALED_FINAL_TREE
        |
        v
crear release raíz R con tree(R) = SEALED_FINAL_TREE
        |
        v
mirror/main = R
        |
        v
verificación independiente
        |
        v
canonical/main = mismo R
        |
        v
verificación final y cierre del proyecto
```

Cada escritura a una rama protegida por este flujo requiere una autorización explícita correspondiente. Autorizar un paso no autoriza automáticamente los siguientes.

## 8. Contrato del árbol sellado y de `main`

El release final debe cumplir:

```text
MIRROR_REVIEW_TREE
=
CANONICAL_REVIEW_TREE
=
MIRROR_MAIN_TREE
=
CANONICAL_MAIN_TREE
=
SEALED_FINAL_TREE
```

Y además:

```text
MIRROR_MAIN_SHA = CANONICAL_MAIN_SHA = R
R.parents = []
```

El `main` histórico actual es un placeholder raíz vacío identificado, en el candidato de gobernanza que introdujo este modelo, como:

```text
LEGACY_MAIN_SHA = 3a1f13574e4a27d9aff2bfd38b3659951e8cb264
LEGACY_MAIN_TREE = 4b825dc642cb6eb9a060e54bf8d69288fbee4904
LEGACY_MAIN_PARENT_COUNT = 0
```

Estos valores son una **precondición histórica**, no una autorización permanente. Deben revalidarse inmediatamente antes de cualquier reemplazo de `main`.

No se debe mergear ni rebasear el release contra ese placeholder. El modelo aprobado es un único commit raíz creado desde el árbol final sellado.

## 9. Excepción lease-guarded y prohibiciones

`BLIND_FORCE = PROHIBITED`.

La única excepción potencial es el reemplazo único de `main` por `R`, siempre que:

- el ref remoto siga exactamente en la precondición esperada;
- el árbol sellado ya haya sido auditado;
- exista autorización explícita para ese repositorio y ese checkpoint;
- el reemplazo esté protegido por lease o mecanismo equivalente de compare-and-swap;
- se publique primero en mirror y se verifique;
- canonical reciba después exactamente el mismo commit `R` con autorización nueva;
- cualquier desviación de SHA o árbol produzca fail-closed.

Este documento **no autoriza por sí mismo** ninguna escritura a `review`, `canonical` ni `main`.

También permanecen prohibidos, salvo autorización específica independiente:

- tags;
- creación de ramas de auditoría innecesarias;
- merges mayoristas de ramas históricas;
- rebase de la historia de integración;
- acciones físicas o HIL;
- cambios de código productivo durante una remediación documental de cierre.

## 10. Criterios para sellar el candidato final

Antes de declarar `SEALED_FINAL_TREE` debe existir evidencia suficiente de que:

1. `README.md`, `TODO.md`, `AGENTS.md` y este contrato son coherentes entre sí;
2. no quedan instrucciones activas contradictorias en la capa documental vigente;
3. los ledgers históricos están claramente tratados como provenance cuando expresan roadmaps superseded;
4. el repositorio no contiene secretos detectados por los gates aplicables;
5. no se reclama validación física actual sin evidencia correspondiente;
6. la estructura documentada coincide con las raíces reales del repositorio;
7. las remediaciones de cierre no introdujeron comportamiento productivo nuevo;
8. el candidato remoto auditado es exactamente el que se promoverá;
9. la publicación final puede reproducir exactamente un único árbol sellado.

La limpieza cosmética, los refactors opcionales y las mejoras que pertenezcan a continuidad futura no bloquean el sellado.

## 11. Definición de proyecto cerrado

OttoGuide queda cerrado cuando, como mínimo:

```text
FINAL_TREE_SEALED = true
MIRROR_REVIEW_VERIFIED = true
CANONICAL_REVIEW_VERIFIED = true
MIRROR_MAIN_ROOT_RELEASE_VERIFIED = true
CANONICAL_MAIN_ROOT_RELEASE_VERIFIED = true
MIRROR_MAIN_SHA = CANONICAL_MAIN_SHA
MIRROR_MAIN_TREE = CANONICAL_MAIN_TREE = SEALED_FINAL_TREE
OPEN_RELEASE_BLOCKERS = 0
ROBOT_ACTIONS_REQUIRED_FOR_CLOSEOUT = 0
```

Las ramas históricas y documentos de provenance pueden permanecer para trazabilidad. Su existencia no implica que el proyecto siga en desarrollo.
